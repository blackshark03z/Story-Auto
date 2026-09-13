# Goal 54 — RQ2 Pre-dispatch Evidence

Date: 2026-09-13
Status: AUTHORIZED / PREFLIGHT_PASS / NOT_STARTED

## Qualification position

RQ1 is `OWNER_APPROVED / PASS`. RQ2 is the second and final independent repeatability sample under `docs/GOAL54_REPEATABILITY_QUALIFICATION_V1.md`. No RQ3 rescue run is allowed.

Frozen RQ2 inputs are identical to X3/RQ1:

- source-frame SHA-256: `5edaecf148914b1230ecf4d3bc0a7f1f80b513cdda9cd71a835471c3e15480ef`
- prompt SHA-256: `8e062a316c0bf5aa329f9baa1cb17f89b892a88d5c72f349c542645011c7f68c`
- model: `seedance-2-fast-i2v`
- duration: `4 s`
- resolution: `480p`
- aspect ratio: `16:9`
- audio: off

## Fresh key-pool preflight

A fresh read-only Elyum preflight was executed immediately before the attempted RQ2 dispatch. Credential contents were not printed or persisted.

- slot 1 balance: `30` credits; quote: `44`; ineligible
- slot 2 balance: `130` credits; quote: `44`; eligible and selected
- estimate hard cap: `44` credits
- selected credential slot: `2`

The budget gate therefore passed.

## Pre-dispatch transient

The first RQ2 launcher attempt returned `PROVIDER_TRANSIENT`. A sanitized ledger read after that attempt confirmed `RQ2 = NOT_STARTED`: no RQ2 clientRef, provider job ID, generation ID, or durable experiment entry existed.

Therefore the failure occurred before a durable RQ2 provider generation was established. No provider job duplication occurred, and no Keep/Kill occurred.

A later retry must first re-confirm `RQ2 = NOT_STARTED`; once any durable RQ2 identity/job exists, the preview launcher must never be called again and all recovery must remain on that same job.

## Boundary

RQ2 remains `NOT_STARTED`. Research is not complete until exactly one RQ2 generation is obtained and visually classified under the frozen X3 rubric. Production promotion remains unauthorized.
