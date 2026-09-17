# Hybrid Visual Elyum Opening engineering candidate evidence

Date: 2026-09-16
Status: ENGINEERING_READY / PRODUCT_MODEL_PREFLIGHT_IMPLEMENTED / PRODUCTION_ROUTING_DISABLED

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

## Productized live-model preflight

Settings `Test connection` now performs the promotion preflight through Story Auto's own credential boundary: it reads `elyum_account`, reads `elyum_models`, extracts Seedance model ids, then calls read-only `elyum_estimate` in `t2v` mode for 6 seconds at 480p. Only model ids whose exact T2V estimate succeeds are returned as verified options, with sanitized credit estimates. No generate/Keep/Kill call is part of this check.

This removes the need for the Tech Lead to read an external key file directly. Production Elyum generation remains disabled until an authorized saved/environment credential actually returns at least one verified Seedance T2V model through this product surface.

Current focused verification: 21 Elyum/provider tests PASS, Python/JS syntax PASS, and `SECURITY_GATE=PASS`. No live generation, Keep, Kill, or credit spend occurred in this qualification.
