# Goal 54 — Production Integration Slice F Evidence

Date: 2026-09-14
Status: LIVE_PREVIEW_READY / VISUAL_ORACLE_PENDING / PRODUCTION_ROUTING_UNCHANGED

## Scope

Slice F qualifies the integrated Full Video production lifecycle, not another provider research recipe. The engineering/UAT harness uses the same canonical `generation_requests.json`, `generation_manifest.json`, run-scoped continuity state, Elyum production adapter, consequence state, render plan and final compositor that production uses. Ordinary Elyum routing remains disabled while the bounded live acceptance surface is still pending.

## Offline production UAT

`tests/test_goal54_slice_f_uat.py` proves a two-shot end-to-end production journey through the real Story Auto production services with a deterministic local provider double:

1. first request starts with an explicit canonical I2V anchor;
2. create persists one provider task, then a transient wait is recovered after a simulated process/app reload by polling the exact saved job only;
3. the exact locked preview is reviewed, Keep is explicit, and only a validated/hash-bound clean output becomes selected;
4. the immediate prior accepted video produces the exact SHA-bound continuity frame for the second request;
5. insufficient credit blocks before upload/create;
6. second preview rejection is recorded, Kill is explicit, and the killed attempt remains immutable;
7. one replacement generation requires a separate explicit Owner authorization and receives a distinct clientRef/attempt identity;
8. the accepted replacement clean output is provenance-bound to its exact reviewed preview;
9. the common renderer produces a final video with audio and complete temporal coverage;
10. rerender is idempotent and does not mutate the generation manifest.

No research ledger participates in this UAT.

## Provider read-only preflight

A zero-generation Elyum MCP preflight was run against the existing two-slot credential pool using the qualified envelope `seedance-2-fast-i2v`, 4 seconds, 480p.

Sanitized result:

- MCP protocol: `2025-06-18`;
- Elyum server: `0.3.0`;
- quote: `44 Credits` per qualified 4-second generation;
- slot 1 balance: `30 Credits` — not eligible for a new qualified generation;
- slot 2 balance: `110 Credits` — eligible for one bounded qualified generation at the current quote;
- no upload, create, Keep, Kill, or other provider mutation occurred during preflight.

The current 110-Credit balance is not treated as blanket authorization for the three-generation worst-case adversarial journey. Any live UAT mutation must proceed sequentially with a fresh read-only preflight before each new provider generation and must stop if `balance < quote` or `quote > 44`.

## Verification

Focused Slice F / Slice E / Elyum / continuity gate:

- `29 passed`;
- `SECURITY_GATE=PASS`;
- `git diff --check` PASS.

Broader application/UI/render/planning/BytePlus/production regression:

- `120 passed, 2 subtests passed`.

Full hermetic repository regression on the same Slice F working tree:

- `767 passed, 283 subtests passed`.

## Bounded live production acceptance surface

Candidate source baseline before live provider mutation: `8b4e34fb7ea61dd80181e28fb25334880b5ec8a5` (`Goal54_prepare_production_slice_F_UAT`). The live probe uses an isolated UAT runtime outside the Git repository and the gated production adapter; ordinary production routing remains disabled.

The first live attempt used credential slot 2 after the recorded balance/quote gate. Exact production identities/evidence:

- project: `prj_goal54_live_uat_20260914a`;
- run: `run_goal54_live_uat_20260914a`;
- request: `req_live_1`;
- provider/model: `elyum_seedance` / `seedance-2-fast-i2v`;
- reference SHA-256: `93dd897729c6370e7cf78b80a1052ac671ff03a36fa824392a75ba198b42a325`;
- durable `client_ref`: `story-auto-prod-9774e1166ea7720219ce9fc6241bdf490c2d616e3328c596`;
- durable provider job: `cos_leYmn4yuIWZosURXvTRbUo:a1056a5a-f249-4695-8a5e-93eb048ccdd5`;
- provider generation: `g_f62ed08940b12f17afdac0ac`;
- `provider_submissions=1`, `attempt_count=1`.

The initial wait cycle ended `WAIT_UNAVAILABLE`. A new local invocation recovered only the exact saved provider job; it did not upload again, create again, or create a second logical attempt. That same job reached `PREVIEW_READY`.

Exact local locked acceptance surface:

- preview SHA-256: `a8c72a65008492638863ccfa31e0e59267e756c6d1d68a538883c0149e92a0f8`;
- contact-sheet SHA-256: `8cfa8716c1602ba2a7de8b360684d8d8db819661f619eab8bb2d544cb96e9d91`;
- H.264, 836x480, 24 fps, 4.041667 seconds, 140051 bytes;
- provider reports `unlock_credits=20`.

A post-preview read-only preflight reports slot 2 balance `90` and the same 4-second/480p quote `44`. Slot 1 remains at `30`. This is recorded only as provider account/consequence evidence; no inference is made about final spend before Keep/unlock.

The exact locked preview was opened locally for the Product visual oracle. No Keep or Kill has run.

## Live V1 visual rejection / prompt correction

The Owner rejected the exact locked preview SHA-256 `a8c72a65008492638863ccfa31e0e59267e756c6d1d68a538883c0149e92a0f8` because motion and facial expression were too stiff. Canonical state is now `PREVIEW_REJECTED`; no Keep/unlock and no Kill has occurred.

Root-cause analysis found that the V1 prompt itself requested an almost locked camera, mostly steady torso/head, a small hand movement and only a subtle blink. The prompt also named an historical X2 step while the canonical production continuity snapshot was bound to the supplied X3 continuity frame. This is a prompt-design failure, not evidence that the provider transport/recovery lifecycle failed.

Correction contract and exact V2 prompt are recorded in `docs/GOAL54_LIVE_UAT_MOTION_ACTING_CORRECTION_V1.md`. Replacement attempts now support a prompt override with immutable prompt SHA-256 and distinct clientRef provenance before provider dispatch. The UI exposes the full revised provider prompt before authorization.

## Remaining acceptance boundary

Transport, identity, local acquisition and same-job recovery are live-verified. Product visual acceptance is not. The next provider mutation, if authorized, is the explicit Kill consequence for the rejected V1 preview, followed by a separately authorized single replacement attempt using the V2 prompt and a fresh read-only balance/quote gate.

Until a corrected live preview passes, Elyum remains `production_enabled=false` and ordinary production routing must remain unchanged.
