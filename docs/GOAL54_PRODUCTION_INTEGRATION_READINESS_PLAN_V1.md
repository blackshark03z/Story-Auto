# Goal 54 — Full Video Production Integration Readiness Plan V1

Date: 2026-09-13
Status: IMPLEMENTATION_READY / REPEATABILITY_QUALIFIED / PRODUCTION_ROUTING_UNCHANGED

## Purpose

Prepare the production architecture for the possibility that the Goal 54 Elyum/Seedance continuity method later becomes `REPEATABILITY_QUALIFIED`, without prematurely routing production traffic through the research adapter.

This document does not authorize provider dispatch, production routing changes, or UI exposure of Elyum.

## Current production truth

Story Auto already has a production Full Video mode: `full_video_ai`.

The accepted production path is currently BytePlus ModelArk:

- provider id: `byteplus_seedance`;
- model: `dreamina-seedance-2-5-260628`;
- transport: first-party async REST task API;
- production generation requests are compiled with provider `byteplus_seedance`;
- Full Video currently suppresses the Flow-era reference-image chain;
- generated Full Video requests have no continuity reference dependencies;
- provider execution/recovery is implemented in `story_auto/providers/byteplus_seedance/service.py`;
- known BytePlus task IDs are safely resumed by polling the same task;
- ambiguous POST results and terminal failures do not auto-redispatch;
- Full Video quality review is manual;
- the creation wizard explicitly requires BytePlus readiness and labels Full Video as BytePlus Seedance.

These facts are consistent with Decision 0002 and must remain unchanged while Goal 54 is only `RESEARCH_CANDIDATE`.

## Research truth from X1C -> X2 -> X3

The accepted Goal 54 research chain is materially different from the current production path:

- provider id: `elyum_seedance`;
- model: `seedance-2-fast-i2v`;
- mode: image-to-video (`i2v`), not prompt-only T2V;
- continuity is carried by an exact deterministic source frame plus an exact prompt;
- provider generation identity is protected by durable `clientRef`/`jobId` state;
- same-job recovery is required after transient waits;
- locked preview review is separated from explicit Keep/Kill consequences;
- cost/balance preflight is part of the safety contract.

Therefore Elyum is not a drop-in replacement for the existing BytePlus T2V adapter. The continuity mechanism proven in research would be lost if production merely changed the provider field while keeping the current Full Video request contract.

## Architectural consequence

If repeatability later passes, Story Auto will have a concrete second API provider plus a second generation capability shape. At that point the condition in Decision 0002 for introducing a provider-selection abstraction is satisfied, but the abstraction must be capability-aware rather than a generic string router.

The production contract must distinguish at least:

- provider identity;
- generation mode (`t2v` versus `i2v`);
- whether a reference image is required/supported;
- durable dispatch/reconciliation semantics;
- live cost/balance preflight availability;
- whether provider-side Keep/Kill or unlock consequences exist;
- supported duration/resolution/aspect-ratio constraints;
- result acquisition and local validation contract.

## Proposed implementation slices after repeatability qualification

### Slice A — Capability contract and provider selection — COMPLETE

Engineering evidence: `docs/GOAL54_PRODUCTION_SLICE_A_EVIDENCE.md`.

Introduce a narrow Full Video provider capability contract. Preserve BytePlus as the default and existing-project behavior. Do not create a broad cross-product provider framework.

A project/run must snapshot the selected Full Video provider and generation capability so later settings changes cannot silently mutate an in-flight job.

Acceptance:
- existing BytePlus projects behave identically;
- provider selection is explicit and durable;
- unsupported capability combinations fail before dispatch;
- no automatic fallback across providers after an ambiguous or charged request.

### Slice B — Continuity-reference lifecycle — COMPLETE

Engineering evidence: `docs/GOAL54_PRODUCTION_SLICE_B_EVIDENCE.md`.

Add the missing production concept required by the validated Elyum method: a deterministic continuity source for each I2V request.

The lifecycle must define:
- how the first shot obtains its canonical anchor;
- how a kept/accepted previous shot yields the exact next continuity frame;
- frame timestamp selection and SHA-256 binding;
- source-frame ownership by request/job snapshot;
- prevention of stale-frame reuse across different runs;
- behavior after manual rejection/replacement.

Do not reuse the old Flow entity-reference chain automatically; Goal 54 continuity is shot-to-shot production continuity, not merely character reference generation.

### Slice C — Elyum production service adapter — COMPLETE

Engineering evidence: `docs/GOAL54_PRODUCTION_SLICE_C_EVIDENCE.md`.

Promote only the minimal proven parts of `story_auto/providers/elyum_seedance/` into a production service that conforms to the generation-manifest authority model.

Required semantics:
- persist stable request identity before provider mutation;
- create at most one provider generation for a logical attempt;
- persist known job identity before waiting;
- recover transient observation by same-job polling only;
- never quality-redispatch automatically;
- acquire locked preview/output with local hash and media validation;
- keep provider consequence actions separate from observation;
- map cost/balance failures into durable product recovery state.

Research ledger files must not become production state. Production must use canonical project artifacts/manifests.

### Slice D — Recovery and consequence state

Extend compact production recovery without weakening BytePlus behavior.

At minimum model separately:
- insufficient provider balance before dispatch;
- pre-dispatch capability failure;
- ambiguous create/reconciliation state;
- known-job transient wait;
- terminal provider failure;
- preview ready / manual QC pending;
- explicit consequence required, when provider semantics require Keep/unlock;
- clean output acquired and hash-bound.

A known job must always resume; an ambiguous or terminal attempt must never silently create a replacement task.

### Slice E — Product UI / observability

Only after runtime semantics are accepted:
- show the configured Full Video provider truthfully;
- show readiness and budget/preflight state before creation;
- preserve Manual QC for video;
- expose current durable job state rather than generic loading;
- show whether Continue will poll an existing job or create a new provider task;
- make any Keep/unlock consequence explicit before spending provider credits;
- do not expose a provider selector when only one provider is actually qualified/available.

### Slice F — Bounded production UAT

Qualification for production integration must prove an end-to-end user journey, not only provider adapter tests:

content/audio -> plan -> Full Video provider preflight -> bounded visual generation -> manual QC -> continuity handoff -> render -> final video.

UAT must include at least:
- fresh run;
- same-job transient recovery;
- insufficient-credit fail-closed behavior;
- app reload/resume with durable provider identity;
- one manual rejection/replacement boundary without duplicate dispatch;
- final artifact provenance and render acceptance.

## Promotion boundaries

RQ1 and RQ2 are both Owner-approved PASS and the aggregate method is now `REPEATABILITY_QUALIFIED`. This clears the research gate for production-integration implementation, but it does not itself switch production routing or authorize unbounded provider spend.

Production mutation must proceed through the bounded slices in this plan with explicit acceptance and regression protection for the existing BytePlus path. Elyum must remain unavailable to ordinary production routing until the required runtime state, continuity lifecycle, recovery semantics, cost policy, observability and bounded UAT are implemented and accepted.

## Immediate next executable step

Slice A is complete and regression-verified. Start Slice B continuity-reference lifecycle before enabling any Elyum production dispatch: canonical first-shot anchor, deterministic accepted-shot frame extraction, SHA binding, request/job ownership, stale-frame prevention and rejection/replacement behavior.
