# Goal 54 — X3 Pre-Dispatch Evidence

Date: 2026-09-13
Status: PRE-DISPATCH GATES PASS / NOT DISPATCHED

## Locked plan

- plan commit: `31512a8dc34b5d36f4e47d2b093a03a876368c57` (`Goal54-lock-X3-spiritual-motion-plan`)
- remote baseline before this evidence: `origin/main` = `31512a8dc34b5d36f4e47d2b093a03a876368c57`
- plan: `docs/GOAL54_X3_PLAN.md`
- X2 baseline: `gen_id=g_d59e88f0244b0717a1b29da6`, status `KEPT`

## Clean X2 provenance

Clean kept X2 was acquired from the existing X2 `download_urls[0]` recorded in `evidence/goal54/xianxia/elyum_xianxia_v1.json`. No new X2 generation was created.

- local path: `D:\Story Auto\evidence\goal54\xianxia\x2_kept_clean.mp4`
- SHA-256: `a70f90bdd0e96ee7d28d1b154c6edf4692f44bec67e6ec2395fd3511f5816e47`
- bytes: `555527`
- duration: `4.041667 s`

## X3 continuity frame

The only allowed X3 reference is a deterministic frame extracted from the clean kept X2 output.

- source timestamp: `3.500000 s`
- local path: `D:\Story Auto\evidence\goal54\xianxia\x3_continuity_frame.png`
- SHA-256: `5edaecf148914b1230ecf4d3bc0a7f1f80b513cdda9cd71a835471c3e15480ef`
- dimensions: `864x496`
- bytes: `460294`

## X3 exact prompt

- local path: `D:\Story Auto\evidence\goal54\xianxia\x3_prompt.txt`
- SHA-256: `8e062a316c0bf5aa329f9baa1cb17f89b892a88d5c72f349c542645011c7f68c`
- characters: `1361`
- content authority: exact prompt in `docs/GOAL54_X3_PLAN.md`

## Fresh Elyum preflight

Read-only MCP preflight completed successfully immediately before dispatch authorization.

- provider plan: `Free`
- available balance: `50` credits
- model: `seedance-2-fast-i2v`
- duration: `4 s`
- resolution: `480p`
- estimate: `44` credits
- budget gate: PASS (`44 <= 44` and `50 >= 44`)
- kill allowance: `1` remaining; X3 must not auto-Kill
- sanitized raw output: `D:\Story Auto\evidence\goal54\xianxia\x3_preflight_output.txt`

## Dispatch boundary

After this evidence is committed and pushed, exactly one X3 preview dispatch is authorized with:

- recipe id `X3`;
- the hash-bound X3 continuity frame above;
- the hash-bound exact prompt above;
- `seedance-2-fast-i2v`, `4s`, `480p`, `16:9`;
- hard max cost `44` credits;
- same-job recovery only for transient waits;
- no redispatch;
- no automatic Keep or Kill.

Visual acceptance remains Owner-controlled according to `docs/GOAL54_X3_PLAN.md`.