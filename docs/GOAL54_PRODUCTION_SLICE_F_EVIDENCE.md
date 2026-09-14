# Goal 54 — Production Integration Slice F Evidence

Date: 2026-09-14
Status: UAT_ENGINEERING_COMPLETE / LIVE_PRODUCT_ORACLE_PENDING / PRODUCTION_ROUTING_UNCHANGED

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

## Remaining acceptance boundary

The production lifecycle itself is engineering-qualified and the adversarial UAT matrix is covered without external mutation. The remaining Goal 54 Slice F boundary is a bounded live production acceptance surface using the gated production adapter under the same qualified envelope.

Do not infer visual Product acceptance from transport success. A live locked preview must retain exact request/job/reference/local-hash provenance and must receive an explicit acceptance oracle before Keep/unlock. Until that live boundary is closed, Elyum remains `production_enabled=false` and ordinary production routing must remain unchanged.
