# Goal 54 — RQ1 Preview Evidence

Date: 2026-09-13
Status: OWNER_APPROVED / PASS

## Qualification identity

RQ1 is the first independent repeatability sample for the frozen X3 method. It uses the exact accepted X3 inputs and settings with no prompt/source tuning.

- recipe: `RQ1`
- provider: `elyum_seedance`
- credential slot: `2` (non-secret slot index only)
- source-frame SHA-256: `5edaecf148914b1230ecf4d3bc0a7f1f80b513cdda9cd71a835471c3e15480ef`
- prompt SHA-256: `8e062a316c0bf5aa329f9baa1cb17f89b892a88d5c72f349c542645011c7f68c`
- model: `seedance-2-fast-i2v`
- duration: `4 s`
- resolution: `480p`
- aspect ratio: `16:9`
- audio: off
- experiment identity SHA-256: `ceb857d06e6969af073ce77f60b63bbb8ee4acbd4f5d3437af0af350389e247c`
- client_ref: `story-auto-g54-ceb857d06e6969af073ce77f60b63bbb8ee4acbd4f5d3437`
- job_id: `cos_leYmn4yuIWZosURXvTRbUo:b3afb79b-977c-4fa1-b5f7-217d9bd5ec82`
- gen_id: `g_76b50dda397f41226d08fcbe`

## Credential-pool / budget evidence

The multiline key pool was preflighted without printing credential contents.

- slot 1 live balance: `30` credits; quote: `44` credits; ineligible
- slot 2 live balance: `150` credits; quote: `44` credits; selected
- provider model/quote: `seedance-2-fast-i2v`, 4 s, 480p, `44` credits
- selected slot was persisted durably as `credential_slot=2`

The earlier single-key `BLOCKED_BUDGET` checkpoint remains historically true for slot 1 but no longer blocks RQ1 after the independently preflighted slot 2 became available.

## Dispatch and recovery proof

1. First key-pool launcher attempt selected slot 2 but failed with `PROVIDER_TRANSIENT` before any RQ1 ledger entry existed; therefore no generation had been dispatched and a pre-dispatch retry was safe.
2. The second launcher reused the same frozen experiment contract. It persisted `credential_slot=2`, the stable `client_ref`, balance/estimate evidence and one provider `job_id` before the local wrapper timed out while waiting.
3. Ledger state was `WAIT_UNAVAILABLE` with the single durable job above. The preview launcher was never called again after that job identity existed.
4. Read-only provider `job_status` polling on slot 2 observed the same job first `running`, then `done`, returning generation `g_76b50dda397f41226d08fcbe`.
5. One same-job `resume` reconciled the ledger to `PREVIEW_READY`.

Exactly one RQ1 provider generation exists. There was no visual-quality redispatch, no second provider job, no Keep and no Kill.

## Locked preview evidence

- local preview: `D:\Story Auto\evidence\goal54\xianxia\rq1_locked_preview.mp4`
- SHA-256: `3cdd424427c1cbf1042c7160e74529023cf90ceb5ebdab74a6a1577c9b772cd9`
- bytes: `121664`
- codec: H.264
- dimensions: `836x480`
- frame rate: `24 fps`
- frames: `97`
- duration: `4.041667 s`
- contact sheet: `D:\Story Auto\evidence\goal54\xianxia\rq1_contact_sheet.png`
- contact-sheet SHA-256: `058fe2c02431c42fad3981640c7973028cd3941caf37fd0e8f015d415456acf9`

The first direct Python acquisition returned HTTP 403 because the media endpoint rejected the default urllib request profile. Re-acquisition with an explicit browser-like User-Agent succeeded against the same signed preview URL; no provider generation or consequence operation was involved.

## Owner visual decision

The Owner explicitly approved the exact locked RQ1 preview after viewing it. RQ1 is therefore classified `PASS` for repeatability qualification. The reviewed artifact remains the exact locked preview with SHA-256 `3cdd424427c1cbf1042c7160e74529023cf90ceb5ebdab74a6a1577c9b772cd9`.

This approval authorizes progression to the single final repeatability sample `RQ2`; it does not authorize Keep/Kill for RQ1 and does not authorize any RQ3 rescue run.

## Acceptance boundary

Technical/provenance acceptance is complete and the Owner visual decision is `PASS`. The governing rubric remains the exact X3 rubric from `docs/GOAL54_REPEATABILITY_QUALIFICATION_V1.md`:

- same adult Chinese female identity;
- matte natural skin / low-gloss material response;
- pavilion, mountains, waterfall and dawn continuity;
- camera almost locked;
- small coherent hand raise;
- faint/localized/translucent pale-blue glow;
- no scene change, extra character, severe anatomy break, large spell effect or style shift.

RQ2 is now authorized as the one final independent repeatability sample. Keep/Kill is not required for repeatability qualification and remains an explicit Owner consequence only.
