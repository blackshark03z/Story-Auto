# Goal 54 — Production Integration Slice E Evidence

Date: 2026-09-14
Status: ENGINEERING_COMPLETE / PRODUCTION_ROUTING_UNCHANGED

## Scope

Slice E adds truthful product UI and observability for the Full Video provider lifecycle already accepted in Slices A–D. It does not enable Elyum production routing and it does not create a provider generation.

## Product-safe projection

`story_auto/application/full_video_product.py` projects only canonical project configuration, `output/generation_requests.json`, and `output/generation_manifest.json` into the ordinary project workspace.

The projection intentionally excludes provider credentials, signed provider URLs and research ledgers. It exposes:

- configured provider and generation mode;
- whether ordinary production routing is enabled or still staged;
- current durable request/attempt status;
- whether a durable provider job is already known;
- safe continuation semantics: new task vs same-job polling vs same-clientRef reconciliation;
- last durable balance/estimate/max-credit preflight evidence;
- Keep/unlock credit consequence when known;
- exact local locked-preview path + SHA-256 and selected clean-output SHA-256;
- the next explicit owner/consequence action.

## Reconciler semantics

The compact production state now understands Elyum-specific durable states instead of passing them through Flow recovery normalization.

Important mappings include:

- known Elyum job -> same-job resume, zero replacement generation authorization;
- saved ambiguous create identity -> same-clientRef recovery only;
- `PREVIEW_READY` -> Owner preview review required;
- `KEEP_REQUIRED` -> explicit Keep/unlock owner boundary;
- `PREVIEW_REJECTED` -> explicit Kill owner boundary;
- `KEEP_ACQUISITION_REQUIRED` -> clean-output acquisition only, never another Keep;
- ambiguous Keep/Kill -> owner reconciliation, automatic consequence retry forbidden;
- `KILLED` / terminal provider outcome -> no automatic replacement generation.

## UI / action boundary

The project workspace renders a dedicated Full Video Provider surface from that projection. The surface shows provider/routing state, continuation safety, durable job presence, preflight/budget evidence and the exact locked preview when present.

Actions are state-driven:

1. Review uses an inline reason field bound to the exact preview SHA-256.
2. Accepting the preview records `KEEP_REQUIRED`; it does not Keep automatically.
3. Keep/unlock requires an explicit confirmation and shows the known unlock-credit consequence.
4. Rejecting the preview records `PREVIEW_REJECTED`; it does not Kill automatically.
5. Kill requires a separate explicit confirmation and reuses the durable rejection reason.
6. A confirmed Keep with missing/failed local clean-output acquisition exposes acquisition-only retry. This retry no longer requires spend confirmation because the service proves Keep is already confirmed and never calls Keep again.
7. Ambiguous Keep/Kill exposes reconciliation only; no retry button performs the consequence again.

The existing Story Auto UX contract that forbids browser `prompt()` remains preserved; review reasons are entered inline.

## Verification

Focused new Slice E + Elyum lifecycle tests:

- `16 passed`

UI + Slice E focused gate after preserving the no-`prompt()` UX contract:

- `22 passed`
- JavaScript syntax PASS
- `git diff --check` PASS

Application regression:

- `18 passed, 2 subtests passed`

Broader Full Video / BytePlus / application / production / release / UI regression:

- `99 passed, 2 subtests passed`
- `SECURITY_GATE=PASS`
- `YOUTUBE_AUTO_RUNTIME_IMPORTS=0`
- Python compile PASS
- JavaScript syntax PASS
- diff check PASS

Full hermetic repository regression on the unchanged Slice E working tree:

- `765 passed, 283 subtests passed`

## Boundary after Slice E

Elyum remains `production_enabled=false` and ordinary production `generate()` remains BytePlus-only. Slice E supplies truthful state and explicit consequence controls for the already-gated Elyum adapter; it does not authorize a live production generation or provider spend.

Next work is Slice F bounded production UAT. Any live UAT provider mutation must remain bounded by the qualified 4-second / 480p / <=44-credit envelope and the explicit consequence rules already proven in Slices C–E.
