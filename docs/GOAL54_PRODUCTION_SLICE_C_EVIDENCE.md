# Goal 54 — Production Integration Slice C Evidence

Date: 2026-09-14
Status: ENGINEERING_COMPLETE / ROUTING_DISABLED / NO_LIVE_PROVIDER_CALL

## Scope

Slice C implements the gated Elyum production service adapter over Story Auto's canonical generation manifest. It reuses the already-qualified MCP transport client but does not reuse Goal 54 research ledger state and does not enable Elyum in Operator routing.

No live Elyum generation, upload, Keep, Kill, or Credit mutation was performed while implementing or verifying this slice.

## Canonical production state

Production execution lives in `story_auto/providers/elyum_seedance/service.py` and writes only the normal `output/generation_manifest.json` plus project-local preview assets.

Before any provider mutation, one exact logical attempt persists:

- run-scoped Slice B continuity snapshot;
- target request identity/fingerprint;
- stable deterministic `client_ref`;
- model/resolution/duration settings inside the qualified envelope;
- read-only live balance/estimate evidence when a real client is later used.

Research JSON ledgers are not read or written by the production adapter.

## Dispatch and recovery semantics

- Production dispatch requires explicit `dispatch_authorized=True`; the adapter otherwise fails before provider access.
- Balance and estimate are checked before reference upload/create. Insufficient balance creates `CREDIT_BLOCKED` with no provider upload/create and no attempt.
- Qualified envelope is currently frozen to `seedance-2-fast-i2v`, provider duration `4 s`, `480p`, max estimate `44 Credits`.
- Exact reference bytes come only from Slice B's run/request/hash-bound snapshot.
- Reference upload is persisted before create so a create retry does not blindly re-upload.
- Ambiguous/transient create records `REPLAY_SAME_CLIENT_REF`; a later invocation replays the same stable clientRef instead of creating a new logical attempt.
- Once a provider `job_id` exists it is persisted before wait; later recovery polls only that same job and never calls create again.
- Terminal provider state never auto-redispatches.
- A provider locked preview is acquired locally, FFprobe-validated and SHA-bound as `preview_asset`; it is not promoted to `selected_asset` and the adapter never calls Keep/Kill automatically.
- A PREVIEW_READY artifact from a prior `run_id` cannot be reused by a later run.

## Continuity ownership hardening

Slice B's provider-boundary check now also treats a canonical production attempt containing `continuity_reference` or `client_ref` as frozen ownership. That prevents rebinding reference bytes after a logical production attempt has been materialized, even if provider upload/create has not yet happened.

## Verification

Offline FakeElyum tests cover:

- explicit dispatch authority;
- cost-block with zero provider mutation;
- manifest snapshot/clientRef persisted before make-video;
- single locked-preview acquisition without automatic Keep;
- ambiguous create -> same-clientRef replay with no second attempt/re-upload;
- wait transient -> same-job resume with no second make call;
- target continuity binding frozen after attempt creation;
- cross-run preview reuse blocked.

Qualification results:

- Slice C + Elyum transport + continuity/provider + planning/BytePlus/application/release/hardening regression: `79 passed, 2 subtests passed`;
- `SECURITY_GATE=PASS`;
- Python compile PASS;
- `git diff --check` PASS.

## Boundary after Slice C

Elyum remains `production_enabled=false` in the Full Video provider capability contract and Operator routing remains BytePlus-only. Slice D must model the explicit preview-review / Keep-unlock / clean-output consequence lifecycle and canonical recovery states before production routing can be enabled.
