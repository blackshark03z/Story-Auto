# Goal 54 — Production Slice D Evidence

Date: 2026-09-14
Status: ENGINEERING_COMPLETE / PRODUCTION_ROUTING_UNCHANGED

## Scope

Slice D closes the provider-consequence and recovery state machine for the qualified Elyum I2V method. It does not enable Elyum production routing and no live provider call or Credit mutation was required for engineering qualification.

## Accepted consequence lifecycle

The canonical generation manifest now separates observation from consequence:

- `PREVIEW_READY` binds the exact locked preview bytes, `gen_id`, provider job identity, continuity snapshot and unlock-cost observation.
- `review_elyum_preview(..., decision="ACCEPT")` records an Owner decision against the exact preview SHA-256 and moves the request to `KEEP_REQUIRED` without calling the provider.
- `review_elyum_preview(..., decision="REJECT")` records the exact rejected preview and moves the request to `PREVIEW_REJECTED` without calling the provider.
- `keep_elyum_preview(..., confirm_spend=True)` is the only Keep/unlock boundary. A Keep intent is durably recorded before the provider call.
- A successful Keep moves to clean-output acquisition. The clean output is locally validated, duration-checked and SHA-256 bound before becoming `selected_asset` / `SUCCEEDED`.
- If Keep is confirmed but clean-output acquisition fails, recovery is acquisition-only (`KEEP_ACQUISITION_REQUIRED`). The Keep action is not repeated.
- If a Keep call has an uncertain outcome, the state becomes `KEEP_AMBIGUOUS`; automatic replay is forbidden.
- `kill_elyum_preview(..., confirm_kill=True)` is the only rejected-preview Kill boundary. A Kill intent and reason are persisted before the provider call.
- If Kill outcome is uncertain, the state becomes `KILL_AMBIGUOUS`; automatic replay is forbidden.
- A confirmed `KILLED` request does not silently dispatch a replacement generation.
- If a previously accepted clean output is later missing or invalid, execution returns to clean-output acquisition recovery only; it does not create, poll, or Keep a new provider generation.

## Safety invariants

1. Owner review is bound to the exact locked-preview SHA-256.
2. Keep/Kill require explicit consequence confirmation.
3. Consequence intent is durable before provider mutation.
4. Ambiguous Keep/Kill outcomes never auto-retry.
5. Confirmed Keep never becomes a second Keep because local acquisition failed.
6. Only a validated clean output can become the canonical selected video asset.
7. BytePlus behavior and default routing are unchanged.
8. Elyum remains production-disabled until Slice E/F product and UAT gates are accepted.

## Verification

- Slice D focused consequence tests: `34 passed` before final hardening.
- Slice D broader regression after acquisition-only recovery hardening: `85 passed, 2 subtests passed`.
- Repository security gate: `SECURITY_GATE=PASS`.
- Full hermetic regression: `761 passed, 283 subtests passed`.
- `git diff --check`: PASS before qualification closure.

## Verdict

`SLICE_D_ENGINEERING_COMPLETE`

Next work: Slice E — product UI / observability. Product surfaces must expose provider truth, durable state, budget/preflight, existing-job-vs-new-dispatch behavior, exact locked-preview review and explicit Keep/Kill consequence boundaries without enabling Elyum routing prematurely.
