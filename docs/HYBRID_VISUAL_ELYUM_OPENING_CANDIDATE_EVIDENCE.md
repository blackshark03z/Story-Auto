# Hybrid Visual Elyum Opening engineering candidate evidence

Date: 2026-09-16
Status: ENGINEERING_READY / LIVE_MODEL_PREFLIGHT_PENDING / PRODUCTION_ROUTING_DISABLED

## Goal

Reuse the existing Elyum Seedance consequence-safe adapter for Hybrid Opening slots without creating a second production pipeline or weakening manual import fallback.

## Candidate behavior

- Hybrid Opening slots use Elyum T2V semantics with an explicit model id supplied by configuration/caller.
- Preflight reads account balance and estimate before dispatch; cost/credit blocks prove no dispatch.
- One deterministic clientRef is persisted before provider creation. Ambiguous create replays the exact same clientRef rather than switching provider or creating a fresh effect identity.
- Locked preview is local, validated and not treated as a READY opening asset.
- Owner ACCEPT moves to KEEP_REQUIRED. Keep requires explicit confirm_spend, and an ambiguous Keep is never automatically retried.
- Owner REJECT moves to PREVIEW_REJECTED. Kill requires explicit confirmation; manual import remains available after Kill.
- Successful Keep downloads the unlocked/original output and feeds the existing import_opening_clip normalization/SHA binding contract.
- Elyum credentials can now use the same Windows DPAPI Story Auto credential store as BytePlus/Pexels, with environment override support.
- Settings exposes Elyum Save/Test/Remove. Test connection is read-only (account balance only) and does not generate or Keep/Kill.

## Verification

- `tests.test_hybrid_opening_elyum`: 6/6 PASS.
- Elyum Opening + Provider Registry + Application regression: 28/28 PASS.
- Windows DPAPI round-trip with a fake test key: PASS; plaintext absent from credential store file.

## Remaining promotion gate

Production Elyum generation remains disabled until a live read-only preflight through an authorized credential source confirms the exact T2V model id/capability for the account. The platform blocked direct access to the historical external key file during this session, so that evidence was not fabricated or bypassed.

No live generation, Keep, Kill, or credit spend occurred in this qualification.
