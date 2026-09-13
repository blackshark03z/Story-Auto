# Goal 54 — RQ2 Preview Evidence

Date: 2026-09-14
Status: TECHNICAL_VERIFIED / VISUAL_PENDING

## Qualification position

RQ2 is the second and final independent repeatability sample under `docs/GOAL54_REPEATABILITY_QUALIFICATION_V1.md`. It used the exact frozen X3/RQ1 source frame, prompt, model, duration, resolution, aspect ratio and audio setting. No prompt/source tuning and no quality redispatch occurred.

## Pre-dispatch and idempotent recovery

Fresh read-only key-pool preflight immediately before the attempt reported:

- credential slot 1: balance `30`, quote `44`, ineligible;
- credential slot 2: balance `130`, quote `44`, eligible;
- model `seedance-2-fast-i2v`, duration `4 s`, resolution `480p`.

The first create attempt entered the durable ledger as `REPLAY_SAME_CLIENT_REF` with the stable client reference below after an ambiguous provider response. No new identity was created. Recovery deliberately replayed the same request identity/client reference only.

- `client_ref=story-auto-g54-758b5c21bd05286f68487abdeccad105ac009f894d90e990`
- `identity_sha256=758b5c21bd05286f68487abdeccad105ac009f894d90e99054764e6a339eaf6c`
- credential slot `2`

The idempotent replay returned one durable provider job:

- `job_id=cos_leYmn4yuIWZosURXvTRbUo:c77849c3-d850-42e0-a9cc-f96b01affc43`

The immediate wait then returned `PROVIDER_TRANSIENT / WAIT_UNAVAILABLE`. From that point onward only same-job resume was used. No second provider job was dispatched.

A subsequent same-job resume reached `PREVIEW_READY`:

- `gen_id=g_2a349ebe471d24bb37a8e9d6`
- provider execution state `done`
- provider-reported unlock cost `20` Credits

A replay-time preflight observed slot-2 balance `110`; this is consistent with provider hold behavior and is not interpreted here as a finalized Keep spend. No Keep or Kill was executed.

## Local acceptance surface

The exact locked provider preview was acquired locally:

- path: `D:\Story Auto\evidence\goal54\xianxia\rq2_locked_preview.mp4`
- SHA-256: `56aee3514dcccca429c918f4d92e0a6768d0b09f889f29dc59fd481b58575598`
- codec: H.264
- frame size: `836x480`
- frame rate: `24 fps`
- frames: `97`
- duration: `4.041667 s`
- bytes: `110115`

Contact sheet:

- path: `D:\Story Auto\evidence\goal54\xianxia\rq2_contact_sheet.png`
- SHA-256: `511d5b30cc6c3decb8983c0786b32acbaa6394fd85cd4040dbbbc065c59df5bf`

This binds the exact acceptance surface to the durable provider identity without relying on gallery order, filenames, timestamps or UI recency.

## Current verdict boundary

Technical/provenance qualification is complete. The exact RQ2 locked preview still requires direct visual classification against the frozen X3 rubric. Automated or structural evidence must not be promoted into a visual PASS under CADS Acceptance Surface Provenance.

Therefore repeatability remains `PENDING_RQ2_VISUAL_ORACLE`:

- RQ1: `OWNER_APPROVED / PASS`
- RQ2: `TECHNICAL_VERIFIED / VISUAL_PENDING`
- RQ3: forbidden by the frozen plan

If the exact RQ2 preview is `PASS` or `PASS_WITH_MINOR_DRIFT` with zero critical failures, Goal 54 may record `REPEATABILITY_QUALIFIED`. Otherwise record `NOT_REPEATABLE`. Locked-preview evidence is sufficient; Keep/Kill is a separate consequence and is not required for qualification.
