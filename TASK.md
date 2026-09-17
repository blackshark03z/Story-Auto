# Goal 54 — Full Video Seedance Provider Qualification

## Gemini 3.8 reasoning baseline — 2026-09-17

- Promote `gemini-3.8-flash` to HARD-first reasoning and new/default project model.
- Preserve deterministic fallback through Gemini 3.7/3.6/3.5 and existing 2.5 safety fallbacks.
- Preserve Flash-Lite BULK routing.
- Remove deprecated sampling parameters from Gemini 3.6+ request shapes while preserving legacy request compatibility.
- SoT: `docs/decisions/0008-gemini-3-8-brain-baseline.md`.


## Goal

Reopen `full_video_ai` as an active development Goal by proving the smallest
reliable Seedance-backed provider path that can produce Story Auto REQUIRED VIDEO
assets with durable provenance and complete final-video coverage. `full_image`
remains release-supported and unchanged while this Goal is evaluated.

## Critical User Journey

1. Create/open a Full Video project and reuse the existing content, audio,
   alignment, planning, approval, generation-request, manifest, and render
   contracts.
2. Dispatch one bounded Seedance VIDEO request through one candidate provider.
3. Acquire a validated local VIDEO asset with request/attempt/provider/model and
   output provenance.
4. Resume or recover without duplicating a confirmed or ambiguous provider
   effect.
5. Expand the qualified path to a representative multi-scene Full Video fixture
   and render the final video through the existing compositor.
6. Start a new run without leaking stale active context from the completed run.

## Acceptance

- At least one Seedance provider path is proven by direct runtime evidence, not
  marketing claims alone.
- Required input/output capabilities, duration/resolution limits, watermark and
  usage constraints, quota/cost visibility, output acquisition, and failure
  behavior are characterized.
- Provider/model, request identity, attempt state, returned asset identity and
  local asset hash/path are preserved when observable.
- Ambiguous provider state cannot cause blind duplicate generation.
- The qualified provider produces a valid local VIDEO asset accepted by existing
  media/render contracts.
- A representative Full Video fixture reaches complete VIDEO coverage and a
  technically valid final render.
- Existing Full Image behavior does not regress.
- No generic provider router is introduced unless concrete variation from a
  second provider proves the abstraction is needed.
- Acceptance is tied to an identified Product HEAD and runtime evidence; isolated
  tests alone are insufficient.
- Any UI/preview/downloaded-media evidence used for Product or Owner acceptance
  must satisfy CADS Acceptance Surface Provenance: the material runtime,
  artifact/assets, configuration and data authorities affecting the claim must
  be traceably associated with the intended candidate, otherwise the criterion
  remains `UNVERIFIED`.

## Acceptance Fixture

Start with one small approved scene containing narration/alignment and one
REQUIRED VIDEO request. Reuse the same semantic request across candidates where
possible. Only after one provider path qualifies, expand to a representative
multi-scene Full Video fixture.

## Non-goals

- Do not reopen `hybrid_hook` in this Goal.
- Do not redesign or replace the accepted `full_image` Google Flow path.
- Do not build a universal provider marketplace/router before demonstrated need.
- Do not rewrite historical provider evidence or unrelated UI/planning/TTS/render
  behavior.

## Constraints

- Git/source is implementation truth; identified runtime evidence is observed
  behavior truth; chat and provider pages are discovery inputs only.
- Preserve ambiguous attempts and completed assets; never infer ownership from
  gallery order, filenames, timestamps, or UI recency alone.
- Prefer `REUSE -> WIRE -> FIX -> REPLACE_AND_DELETE -> ADD`.
- Free/trial access helps qualification but does not by itself prove production
  reliability.
- Credentials and provider secrets must not enter committed source/evidence.

## Material Decisions

- Owner decision 2026-09-10: reopen Full Video provider qualification with
  Seedance as the current model family under investigation.
- `full_image` remains the accepted production path during this Goal.
- Provider winner is intentionally UNDECIDED until direct evidence exists.
- Initial research queue includes Dola, Dreamina, Elyum, Pollo, DeeVid, AdSkull,
  and additional Seedance-access providers discovered during research. Presence
  in the queue is not acceptance.
- Start with one provider-specific vertical slice; generalize only after real
  second-provider variation justifies it.
- Stability decision 2026-09-12: the production Full Video path must be API-first
  and must expose durable task/job identity plus polling or an authenticated
  callback contract. Browser/UI automation is not an accepted production
  transport for this Goal.
- Dola/Dreamina browser surfaces and other UI-only routes remain research/demo
  surfaces only. They are not production candidates because session/UI drift can
  recreate the connection and attribution failures previously observed with Flow.
- First implementation baseline: BytePlus ModelArk first-party Seedance 2.5
  (`dreamina-seedance-2-5-260628`) through the official asynchronous contents
  generation API.
- Free-first verification on 2026-09-12 reopens only API-first third-party
  candidates that pass the same stability gate. Elyum is the first candidate to
  preflight because official docs state 150 free credits with no card, one shared
  Web/MCP/REST balance, durable `jobId`, job-status/wait operations and
  idempotent `clientRef` create semantics. BytePlus remains the stable first-party
  baseline/fallback until direct Elyum runtime evidence proves otherwise.
- Pollo passes the API stability gate at documentation level, but its guaranteed
  free API balance is unverified; consumer free credits must not be assumed to
  transfer to the separate Pollo API wallet.
- Owner decision 2026-09-13: open a bounded `XIANXIA_3D_V1` research branch after
  R1. This is a visual-method/continuity experiment, not a provider-routing
  change. Decision Record `0003` and
  `docs/GOAL54_XIANXIA_3D_RESEARCH_PLAN_V1.md` are the canonical contract.

## Progress

- CADS refreshed from `origin/master` on 2026-09-13 at `292bee9`
  (`Require_acceptance_surface_provenance`). The frozen Standard/Five Controls
  remain unchanged. Story Auto applies both the conditional Architecture
  Description rule from `432a19a` and the new Acceptance Surface Provenance
  invariant for observed UI/preview/artifact evidence.
- Baseline before Goal 54: `48947dc` (`Clean accepted product baseline`).
- Goal 54 SoT/CADS framing committed and pushed at
  `77b7bde9c257495a72c21aeee09c064797027182`.
- Story Auto already contains provider-neutral generation requests/manifests,
  VIDEO media contracts, full-video partitioning, and the common compositor.
- Stage A is closed by the 2026-09-12 stability decision: production research no
  longer spends time on browser/UI routes or third-party aggregators while the
  first-party BytePlus path remains viable.
- BytePlus ModelArk Seedance 2.5 is wired as a narrow Full Video adapter: direct
  async task creation, immediate durable task-ID persistence, safe polling/resume,
  local validated acquisition, and no blind redispatch after ambiguous POST or
  terminal provider failure.
- Full Video generation requests now use `byteplus_seedance` and do not create
  Flow reference-image dependencies. Full Image remains on Google Flow.
- Full Video is exposed in New Video and uses `MANUAL_REVIEW` until automated
  temporal/video quality acceptance is separately proven.
- API-first Full Video implementation checkpoint: `d2c32745ef1f551f1ef924378b83628464bbde79`
  (`Goal54-stable-api-first-Seedance-path`).
- Post-implementation focused gate passes 41/41 `unittest` tests plus JavaScript
  syntax validation and `git diff --check`.
- Full hermetic regression (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`) reaches 100% with
  714 tests passed and 283 subtests passed. The ChatCode wrapper reported a
  process timeout only after pytest printed the complete PASS summary.
- A zero-generation live BytePlus preflight is implemented at
  `tools/goal54_seedance_preflight.py`.
- Elyum read-only MCP preflight is implemented at
  `tools/goal54_elyum_preflight.py`. It can call only initialize/tools-list plus
  `elyum_account`, `elyum_models`, and `elyum_estimate`; it has no generation,
  keep, kill, upload, or mutation path. Offline sanitizer/protocol tests pass 4/4.
- Real Elyum Free-account preflight PASS: plan Free, balance 150, kill limit/left
  1/1, MCP protocol 2025-06-18, server 0.3.0, account/models/estimate read tools
  callable. Live 4s/480p estimates are Fast T2V 44, Mini T2V 64, 2.5 T2V 76,
  Fast I2V 44 and 2.5 Reference 76 Credits. 2.5 I2V estimate timed out once and
  remains unverified.
- Live MCP schema probe PASS: video creation is `elyum_make_video`, not a generic
  `elyum_generate`. It accepts idempotent `clientRef`, mode/model/prompt,
  imageUrl/imageUrls, duration/aspectRatio/resolution/audio and returns `jobId`.
  `elyum_wait` explicitly requires retrying the same `jobId` after timeout; it
  must never trigger resubmission. `elyum_keep` is documented as the only action
  that spends Credits. `elyum_kill` releases the hold but consumes kill allowance.
  `elyum_upload` accepts URL or base64 media and is documented as free.
- Free+stable provider verification is persisted in
  `docs/GOAL54_FULL_VIDEO_SEEDANCE_PROVIDER_EVIDENCE.md`: Elyum is
  `FREE_STABLE_API_CANDIDATE_HIGH`; Pollo is `STABLE_API / FREE_API_UNVERIFIED`;
  AdSkull is `FREE_API_CANDIDATE_MEDIUM` pending stronger task/retry evidence.

## Discoveries / Blockers

- ChatCode's registered Story Auto workspace is a parent directory; the actual
  Git repository is nested at `story-auto/`. Git commands must use that directory
  as cwd.
- Historical provider-baseline records closed provider selection around Google
  Flow. Goal 54 supersedes that closure only for Full Video qualification; Full
  Image remains unchanged.
- Browser/UI-only providers are intentionally not investigated further for the
  production path because connection/session drift is a known unacceptable risk
  for this Goal.
- Live BytePlus preflight on 2026-09-12 reached no provider call because the Story
  Auto process has no configured `BYTEPLUS_MODELARK_API_KEY`, `BYTEPLUS_API_KEY`,
  or `ARK_API_KEY`. This is a BytePlus Stage B blocker; it is not an engineering
  PASS or provider failure.
- The Owner's real logged-in Elyum Free account confirms 150 starter Credits and
  one current-period kill. The API key is kept outside the repository.
- Elyum Free developer/MCP access is proven by runtime evidence. R1 dispatched
  exactly one Fast-I2V job using the durable pre-recorded `clientRef`; transient
  wait failure recovered by the same `jobId` without a second make call.
- R1 was explicitly Kept by the Owner. A post-Keep read-only account preflight on
  2026-09-13 reports balance **130 Credits** (down from 150 by the provider's
  reported 20-Credit unlock price) and kills left **1/1**, confirming the bounded
  consequence without consuming the kill allowance.
- The old R2-first 2.5-Reference direction is paused. The accepted next research
  branch is `XIANXIA_3D_V1`, which restarts visual-method evidence with one new
  canonical GPT Image anchor and one Fast-I2V X1 preview before any continuity
  expansion.
- Canonical Xianxia anchor provenance is now complete locally: GPT Image source
  generation `5eb96ca5-da11-4d7e-b615-7e1e9fef1726` was deterministically
  normalized to `D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_f01_anchor.png`,
  1280x720, SHA-256
  `d8a48a3e725b8511250f84506458bcdf2d13e4f2e9a73cabd8c3f4f5eb2ae96b`.
- Exact X1 prompt is frozen at
  `D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_prompt.txt`, SHA-256
  `e28c57c545a1c606c13df1637664ace5c9718304ca85bea3afcfa70d563592da`.
  Anchor and prompt hash mismatches block dispatch under CADS acceptance-surface
  provenance. Source checkpoint before X1 dispatch: `2d03bd065fa03d1cf112dfc9b33ac0b8bf2fe682`.

## Historical Next Safe Action (superseded 2026-09-13)

Keep the BytePlus implementation and regressions green as the stable fallback.
Use `docs/GOAL54_SHOT_RECIPE_EXPERIMENT_V1.md` as the bounded cinematic research
contract. The research-only Elyum adapter is implemented under
`story_auto/providers/elyum_seedance/` without changing product routing. It
supports free reference upload, live estimate, idempotent make-video with stable
`clientRef`, durable research ledger `jobId`, same-job wait/resume, and explicit
keep/kill decisions; no automatic Credit spend exists. Pre-dispatch gate passes
63/63 tests plus JS syntax/diff checks. The deterministic R1 character fixture
was generated outside Git at SHA-256
`31ca872d7b608dee61db0f0bdc753e4acaf659c428706ff7da88dfee98c3e531`
and uploaded successfully through `elyum_upload` (documented free).

R1 runtime qualification has now crossed the first real generation boundary.
The first call failed pre-dispatch with `PROVIDER_TRANSIENT`; read-only recheck
then confirmed balance 150 and quote 44. A retry reused the exact same durable
`clientRef`, returned provider job
`cos_leYmn4yuIWZosURXvTRbUo:cb35e5fa-f9c9-4763-81fc-523c2b9073b1`, and a
transient `elyum_wait` failure was recovered by polling that same job only. The
result is now `PREVIEW_READY` / locked with generation
`g_e2fa8c99efa9300c0e792ebd`; provider runtime reports Keep/unlock cost 20
Credits. The locked preview was acquired locally at
`D:\Story Auto\evidence\goal54\r1_locked_preview.mp4`, SHA-256
`f9f0b5cdae2044eb508e276e5031f678e92539fb21471a537184770cc3122e9a`, H.264,
836x480, 24 fps, 4.041667 s. Automated motion evidence shows no hard cut (cut-spike ratio 1.526), but its
first-to-last affine scale metric (0.9999) was a misleading proxy for this stylized
clip. Direct review of the uploaded video/contact sheet supersedes that inference:
the framing clearly tightens from medium toward close-up across 0% -> 100%, so
the requested slow push-in is visibly present and smooth. Identity markers
(teal bob, red round glasses, mustard jacket, blue shirt, triangle earrings and
beauty mark) remain stable; the window/sofa/plant layout stays coherent; no hard
cut, scene replacement, severe anatomy defect or obvious identity swap is visible.
The requested slight head turn is present only subtly, so subject-action compliance
is weaker than camera compliance. Provisional visual rubric is 9/10 (camera 2,
subject action 1, identity 2, environment 2, anatomy/physical motion 2) with no
critical-failure flag. R1 is therefore `RESEARCH_CANDIDATE`, not yet
`REPEATABILITY_PROVEN`. The Elyum preview watermark/lock overlay is provider
preview UI evidence, not treated as a generation-content defect. Keep would cost
20 Credits and still requires explicit Owner approval; Kill would consume the
account's sole current-period kill allowance. BytePlus remains the stable
production fallback; Pollo stays deferred until its API wallet itself proves
usable free credit.

## Next Safe Action

Keep BytePlus and the accepted Full Image path unchanged. R1 remains preserved as
provider/recovery evidence and is now Kept; do not continue the old R2 plan.

Execute `docs/GOAL54_XIANXIA_3D_RESEARCH_PLAN_V1.md` in order:

1. generate exactly one canonical `XIANXIA_F01` / `XIANXIA_ENV_PAVILION_01`
   16:9 anchor with GPT Image in one generation step;
2. store it outside Git under `D:\Story Auto\evidence\goal54\xianxia\`, hash it
   and record only identity/evidence metadata in Git;
3. read-only recheck Elyum balance and Fast-I2V 4 s estimate;
4. dispatch only X1 (`SLOW_PUSH_IN + HOLD_WITH_MICROMOTION`) with a new xianxia
   ledger/clientRef and hard cost bound;
5. recover the same job to locked preview, acquire it locally, score the xianxia
   rubric, then stop for explicit Keep/Kill.

X2 Continuity is authorized only after a passing, explicitly Kept X1 and must use
a clean frame from X1 as its input. X3 Spiritual Motion and optional Seedance 2.5
Reference A/B remain conditional on evidence and current Credit balance. No
production routing/UI/planner integration is authorized by this research branch.

Current Xianxia anchor state: canonical GPT Image bytes are present locally at
`D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_f01_anchor.png`, 1280x720,
SHA-256 `d8a48a3e725b8511250f84506458bcdf2d13e4f2e9a73cabd8c3f4f5eb2ae96b`.
The exact X1 prompt is frozen outside Git at
`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_prompt.txt`, SHA-256
`e28c57c545a1c606c13df1637664ace5c9718304ca85bea3afcfa70d563592da`.

X1 has now crossed the provider boundary exactly once from candidate source HEAD
`b1c3ea61fb356939f663137ae71f6f35ac8b21b7`. Live pre-dispatch evidence was
balance 130 Credits and Fast-I2V 4 s / 480p estimate 44. Durable identity:
`client_ref=story-auto-g54-3604b3b68a1483f2692154ddd1f0a46e326356c37090aad6`,
`job_id=cos_leYmn4yuIWZosURXvTRbUo:7e7856b2-3d90-42ff-ae0b-7a2664510d62`,
`gen_id=g_c94da17e6dfeb2f8814a7648`. Two transient `elyum_wait` observations were
recovered against that same job only; no second make-video dispatch occurred.
Provider state is now `done` / ledger `PREVIEW_READY`, with one locked preview and
reported `unlockCredits=20`.

The exact acceptance surface for X1 is locally acquired at
`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_locked_preview.mp4`, SHA-256
`b89e5b057a8a83534abb26d73d3e6ac6f7404a151f7c617496839f6a0baf48eb`, H.264,
836x480, 24 fps, 97 frames, duration 4.041667 s. Contact-sheet evidence is
`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_contact_sheet.png`, SHA-256
`03589216d946f187b6792974fceae3738b7ff74188ab09e8829630883c3ca10f`.
Technical acquisition/provenance is verified. Owner visual review on 2026-09-13
classified X1 as `PARTIAL_FAIL_STYLE_SURFACE`: identity/scene/camera evidence is
useful, but skin and scene materials are too glossy/plastic for the intended 3D
xianxia target. The requested correction is lower gloss/specular response and
higher softness. X1 is preserved as evidence, **must not be Kept**, and need not
consume the sole Kill allowance. X2 remains blocked. X1b Matte-Soft Retry has now been dispatched exactly once
from source HEAD `3db9824842dcdb30d9847aaeb69bb5682f1df859`, reusing the same
canonical anchor and changing only the style-surface prompt. Exact X1b prompt is
`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1b_prompt.txt`, SHA-256
`a0886dfee4f36c4eb5f1d82c477d5545e1a8573fb1735f26b6d6a7d5d5d04cc9`.

X1b durable identity is
`client_ref=story-auto-g54-567726916bd2328faad0131f8f6bb09507d7e108683fae43`,
`job_id=cos_leYmn4yuIWZosURXvTRbUo:201a6c7a-9353-4f72-901d-88c6669522f8`,
`gen_id=g_c6de972a60efff3178c8152f`. After transient wait/resume observations,
the same job reached `PREVIEW_READY`; no redispatch occurred. Locked preview is
`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1b_locked_preview.mp4`, SHA-256
`d15b5a3d727998fef8465bc297a4355e24d218e49d342cc9304934478586338c`,
H.264 836x480, 24 fps, 4.041667 s. Provider reports `unlockCredits=20`.

Available balance was 110 before X1b and 90 after X1b, with kills still 1/1.
Treat this as provider hold evidence rather than final spend: Elyum documents that
generation holds Credits, Keep finalizes the charge, and Kill releases the hold.
X1 and X1b remain locked/unkept. X1b visual acceptance remains useful research evidence but the current direction is paused before any Keep/Kill or X2 work. The next research step is recorded in `docs/GOAL54_XIANXIA_ANCHOR_V2_CHECKPOINT.md`: create and visually accept one GPT Image `XIANXIA_ANCHOR_V2` with matte skin, soft diffuse lighting, soft-satin fabric and restrained localized reflections, then test that still with the concise reference-first Seedance prompt architecture. Do not spend another video preview until the V2 still itself passes the Owner material/style oracle.
A matched A/B sheet is at
`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_vs_x1b_compare.png`, SHA-256
`6dc74c0d81ffd81d0cd5669000cc7923fd87f836ba759875d0b28ed49f0a2616`.
Supporting global image metrics show reduced highlight fraction (`0.096964 ->
0.084539`) and mean luma (`0.535632 -> 0.499830`) in X1b, but they do not replace
the Owner oracle for skin/material softness.

Prompt Research V1 is now durable at `docs/GOAL54_SEEDANCE_PROMPT_RESEARCH_V1.md`.
The research separates long-form Visual Constitution (anchor/reference creation)
from short-form Seedance Shot Prompt (reference lock + one material/style delta +
one subject motion + one camera move + 3–6 critical constraints). Candidate X1C
is defined there as a concise reference-first/motion-first matte-soft prompt, but
**is not yet dispatched**. X1B visual review is superseded as the immediate next oracle by the Owner-selected Anchor V2 still; X2 remains blocked.\n\nX1C has now been dispatched exactly once and recovered through the same durable provider job to `PREVIEW_READY`; no redispatch, Keep, or Kill occurred. Technical/provenance evidence is durable at `docs/GOAL54_X1C_PREVIEW_EVIDENCE.md`. Locked preview SHA-256 is `011ddec32d66f4db2ac549669c80cfaf3f428c05c4132567b06445f4a50f1b66`; provider identity is `job_id=cos_leYmn4yuIWZosURXvTRbUo:39c7c363-51be-46b1-87c1-661b8ddfffa1`, `gen_id=g_1e1719f8fdf634aa8f064d90`. X1C is `TECHNICAL_VERIFIED / VISUAL_UNVERIFIED`; Owner review of the actual preview is the next acceptance oracle, and X2 remains blocked until that passes.

The Owner has now selected a new `XIANXIA_ANCHOR_V2` still direction after correcting the previous white/glossy skin and overly bright/reflective environmental materials. Exact bytes are now locally provenance-bound at `D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_anchor_v2.png`, 1672x941 PNG, SHA-256 `569030979570518ca7ed7fedd9499065f499b11977eb5131ce436dad5e5ca42c`, matching the Owner-selected candidate byte-for-byte. Anchor V2 therefore clears the local provenance gate for X1C dispatch. X1C concise prompt is frozen at `D:\\Story Auto\\evidence\\goal54\\xianxia\\x1c_prompt.txt`, SHA-256 `ed71f3e6edbee061427b9efc1fa265dd4bddd6637adaf3d604b3313d46e552bc` (909 chars). After local anchor binding, the next safe provider action is one Fast-I2V 4 s / 480p X1C preview with a fresh balance/estimate, hard cost bound, durable new clientRef/jobId, and no automatic Keep/Kill.

## Goal 54 X2 Keep checkpoint
- X2 is `KEPT` on Elyum: `gen_id=g_d59e88f0244b0717a1b29da6`.
- Evidence: `docs/GOAL54_X2_KEEP_EVIDENCE.md`.
- X2 is the promoted continuity baseline after X1C; do not redispatch X2.
- Clean X2 provenance is now bound and the X3 plan is locked in-repo.

## Goal 54 X3 pre-dispatch checkpoint
- Evidence: `docs/GOAL54_X3_PRE_DISPATCH_EVIDENCE.md`.
- Clean X2 SHA-256: `a70f90bdd0e96ee7d28d1b154c6edf4692f44bec67e6ec2395fd3511f5816e47`.
- X3 continuity frame at 3.500000 s SHA-256: `5edaecf148914b1230ecf4d3bc0a7f1f80b513cdda9cd71a835471c3e15480ef`.
- X3 exact prompt SHA-256: `8e062a316c0bf5aa329f9baa1cb17f89b892a88d5c72f349c542645011c7f68c`.
- Fresh Elyum read-only preflight PASS: balance `50`, estimate `44`, model `seedance-2-fast-i2v`, `4s`, `480p`.
- Exactly one X3 preview was dispatched after this checkpoint was pushed; same-job recovery only was used; no automatic Keep/Kill occurred.

## Goal 54 X3 preview checkpoint
- Evidence: `docs/GOAL54_X3_PREVIEW_EVIDENCE.md`.
- X3 is `PREVIEW_READY` on Elyum: `job_id=cos_leYmn4yuIWZosURXvTRbUo:90981d0a-4963-45f6-8547-22cded994c38`, `gen_id=g_a18de93d00316ba4dbbe32ba`.
- Locked preview SHA-256: `8c916375cf3ab76b22dbf69da1e1749a9425396632c0c6696ade185be3ca518b`.
- Contact-sheet SHA-256: `718a2a167f540d46e9b92866112ee7757fe69817223cf361ace4d9353655aeee`.
- Recovery preserved the single provider job across transient waits; no redispatch, Keep, or Kill occurred.
- Technical/provenance verification is complete. Owner visual review against `docs/GOAL54_X3_PLAN.md` is the next acceptance oracle; no later experiment is authorized yet.

- Assistant visual review of the exact uploaded locked preview: `PASS_WITH_MINOR_DRIFT`; the Owner then explicitly approved X3.

## Goal 54 X3 Keep checkpoint
- X3 is `KEPT`: `job_id=cos_leYmn4yuIWZosURXvTRbUo:90981d0a-4963-45f6-8547-22cded994c38`, `gen_id=g_a18de93d00316ba4dbbe32ba`.
- Keep evidence: `docs/GOAL54_X3_KEEP_EVIDENCE.md`.
- Clean kept X3 SHA-256: `8da1d34734f83d8131812f619490b6c0a358948d7e9a9cbc8518883fac24976f`.
- X1C → X2 → X3 is now a completed bounded `RESEARCH_CANDIDATE` chain; do not auto-promote it into production routing from one passing chain.
- Next safe step is repeatability qualification planning. No X4 or other provider generation is authorized by this checkpoint.

## Goal 54 repeatability qualification checkpoint
- Plan: `docs/GOAL54_REPEATABILITY_QUALIFICATION_V1.md`.
- Baseline X3 is `KEPT` / `RESEARCH_CANDIDATE`: `gen_id=g_a18de93d00316ba4dbbe32ba`.
- Frozen source-frame SHA-256: `5edaecf148914b1230ecf4d3bc0a7f1f80b513cdda9cd71a835471c3e15480ef`.
- Frozen prompt SHA-256: `8e062a316c0bf5aa329f9baa1cb17f89b892a88d5c72f349c542645011c7f68c`.
- Qualification consists of at most two independent provider samples, `RQ1` then `RQ2`, using the exact same source frame, prompt, model, duration, resolution, aspect ratio and audio setting as X3.
- No prompt/source tuning between X3, RQ1 and RQ2; no visual-quality redispatch; no RQ3 rescue run.
- Each repeat requires a fresh read-only Elyum balance/estimate preflight immediately before dispatch; quote must be `<=44` and live balance must cover it.
- RQ2 is not authorized until RQ1 locked preview has been provenance-bound and visually reviewed against the X3 rubric.
- Repeatability may promote only when RQ1 and RQ2 each reach `PASS` or `PASS_WITH_MINOR_DRIFT` with zero critical failures and zero quality redispatches.
- Locked preview is sufficient for repeatability evidence. Keep/Kill remains a separate explicit Owner consequence and is not required for qualification.

## Goal 54 RQ1 budget checkpoint
- Fresh read-only Elyum preflight after the qualification plan was pushed: balance `30`, estimate `44`, model `seedance-2-fast-i2v`, `4s`, `480p`.
- RQ1 is `BLOCKED_BUDGET` because `30 < 44`; no provider generation was dispatched.
- Evidence: `docs/GOAL54_RQ1_BUDGET_BLOCK_EVIDENCE.md`.
- Do not weaken the frozen X3 inputs/settings to fit budget. RQ1 remains `NOT_STARTED` until a future fresh preflight covers the exact contract.
- RQ2 remains unauthorized and the method remains `RESEARCH_CANDIDATE`, not `REPEATABILITY_QUALIFIED`.

## Goal 54 production-integration readiness checkpoint
- Planning-only integration analysis is recorded at `docs/GOAL54_PRODUCTION_INTEGRATION_READINESS_PLAN_V1.md`; production routing is unchanged.
- Current Full Video production is BytePlus prompt-only T2V with provider-specific durable task recovery; Goal 54's accepted research method is Elyum I2V with an exact continuity frame, cost preflight and explicit consequence semantics.
- Elyum therefore is not a drop-in provider-string replacement. If repeatability later qualifies it, integration requires a capability-aware provider contract plus a shot-to-shot continuity-reference lifecycle while preserving BytePlus behavior.
- No Elyum production routing, provider selector, or production adapter promotion is authorized until RQ1 and RQ2 both pass and the method reaches `REPEATABILITY_QUALIFIED`.

## Goal 54 Elyum credential-pool checkpoint
- The Elyum research tooling supports a multiline credential pool without logging credential contents.
- Read-only preflight can inspect every non-empty slot and returns only sanitized slot index, account balance, estimate, and provider metadata.
- RQ1 must select a slot only when its own live balance covers the quote; no cross-account balance inference is allowed.
- The chosen non-secret `credential_slot` is persisted in the experiment ledger so same-job recovery and any later explicit consequence reuse the same provider account.
- Targeted Elyum regression: `12 passed`; Python compile and `git diff --check` PASS before commit.

## Goal 54 RQ1 preview checkpoint
- RQ1 budget gate passed through credential slot `2`: live balance `150`, quote `44`; slot `1` remained insufficient at `30`.
- RQ1 is `PREVIEW_READY`: `job_id=cos_leYmn4yuIWZosURXvTRbUo:b3afb79b-977c-4fa1-b5f7-217d9bd5ec82`, `gen_id=g_76b50dda397f41226d08fcbe`, `credential_slot=2`.
- Exactly one provider generation was dispatched. A pre-dispatch transient occurred before any RQ1 ledger entry; after the durable job existed, recovery used only same-job status/resume.
- Locked preview SHA-256: `3cdd424427c1cbf1042c7160e74529023cf90ceb5ebdab74a6a1577c9b772cd9`; contact-sheet SHA-256: `058fe2c02431c42fad3981640c7973028cd3941caf37fd0e8f015d415456acf9`.
- Evidence: `docs/GOAL54_RQ1_PREVIEW_EVIDENCE.md`.
- Technical/provenance verification is complete. The Owner reviewed the exact locked preview and approved RQ1 as `PASS`. No Keep/Kill was executed.

## Goal 54 RQ1 approval / RQ2 authorization checkpoint
- RQ1 is `OWNER_APPROVED / PASS` on locked preview SHA-256 `3cdd424427c1cbf1042c7160e74529023cf90ceb5ebdab74a6a1577c9b772cd9`.
- RQ1 required exactly one provider generation and zero quality redispatches; Keep/Kill remains unnecessary for repeatability.
- RQ2 is now authorized as the second and final independent repeat using the exact frozen X3 frame, prompt, model and settings.
- Before RQ2 dispatch, run a fresh read-only key-pool preflight and select only a credential slot whose live balance covers the current quote.
- After RQ2 visual verdict, stop the research phase: promote to `REPEATABILITY_QUALIFIED` only if RQ2 also passes; otherwise record `NOT_REPEATABLE`. No RQ3 rescue run is allowed.

## Goal 54 RQ2 pre-dispatch checkpoint
- RQ2 frozen contract is unchanged from X3/RQ1; evidence: `docs/GOAL54_RQ2_PRE_DISPATCH_EVIDENCE.md`.
- Fresh key-pool preflight: slot 1 balance `30`, slot 2 balance `130`, quote `44`; slot 2 is eligible.
- First RQ2 launcher attempt returned `PROVIDER_TRANSIENT`, but sanitized ledger verification afterward showed `RQ2 = NOT_STARTED`; no durable clientRef/job/gen was created.
- Historical note: at this checkpoint no RQ2 generation, Keep, or Kill existed yet. That state has now been superseded by the RQ2 preview checkpoint below.

## Goal 54 RQ2 preview checkpoint
- Evidence: `docs/GOAL54_RQ2_PREVIEW_EVIDENCE.md`.
- RQ2 preserved the exact frozen X3/RQ1 input contract and used credential slot `2`.
- The first create observation became `REPLAY_SAME_CLIENT_REF`; recovery reused the same durable `client_ref` and did not create a new request identity.
- One durable provider job was established: `job_id=cos_leYmn4yuIWZosURXvTRbUo:c77849c3-d850-42e0-a9cc-f96b01affc43`.
- A transient wait was recovered only against that same job; RQ2 is now `PREVIEW_READY` with `gen_id=g_2a349ebe471d24bb37a8e9d6`.
- Exact local locked preview SHA-256: `56aee3514dcccca429c918f4d92e0a6768d0b09f889f29dc59fd481b58575598`; contact-sheet SHA-256: `511d5b30cc6c3decb8983c0786b32acbaa6394fd85cd4040dbbbc065c59df5bf`.
- Technical/provenance verification is complete; no Keep/Kill occurred.
- Owner explicitly approved the exact RQ2 locked preview on 2026-09-14 as `PASS`.
- Aggregate Goal 54 repeatability verdict is now `REPEATABILITY_QUALIFIED`: X3 accepted/kept, RQ1 PASS, RQ2 PASS, zero critical failures and zero visual-quality redispatches. No RQ3 was run or is authorized.
- Production routing remains unchanged until bounded integration slices are implemented and accepted.

## Goal 54 production integration Slice A checkpoint
- Slice A is complete; evidence: `docs/GOAL54_PRODUCTION_SLICE_A_EVIDENCE.md`.
- Full Video now has a narrow capability-aware provider contract and durable generation-request provider snapshot.
- BytePlus remains the default and only production-enabled provider; historical projects without the new setting still resolve to BytePlus without mutation.
- Elyum is represented as the qualified I2V capability shape but remains production-disabled and fails closed before dispatch until continuity lifecycle + production adapter work land.
- Targeted regression: `21 passed`; broader application/release/binding regression: `53 passed, 6 subtests passed`; compile and diff checks PASS.
- Slice B is now engineering-complete; evidence: `docs/GOAL54_PRODUCTION_SLICE_B_EVIDENCE.md`.
- Canonical I2V continuity state is run-scoped and generation-request-hash-scoped; the first request requires an explicit canonical anchor and later requests derive a deterministic hash-bound frame only from the immediate prior accepted video.
- Rejected/replaced source assets invalidate or supersede old bindings; a target reference cannot change after that target has entered any provider boundary.
- Targeted continuity/provider tests: `11 passed`; broader planning/BytePlus/application/release regression: `55 passed, 2 subtests passed`; compile/diff checks PASS.
- Full hermetic regression reached `748 passed, 283 subtests passed`; its sole security-gate failure was a pre-existing signed-looking synthetic Elyum fixture. After hardening that fixture, `SECURITY_GATE=PASS` and focused Elyum + hardening tests passed `18/18`, closing the differential qualification gate.
- Slice C is engineering-complete; evidence: `docs/GOAL54_PRODUCTION_SLICE_C_EVIDENCE.md`.
- The gated Elyum production adapter now uses only canonical generation-manifest state plus the exact Slice B continuity snapshot; research ledgers are not production state.
- Stable `client_ref` and continuity ownership are persisted before provider create; ambiguous create replays only the same clientRef, known jobs resume only the same job, and locked preview acquisition is local/hash-bound with no automatic Keep/Kill.
- Cross-run preview reuse is blocked and a materialized production attempt freezes its reference binding before provider mutation.
- Slice C regression: `79 passed, 2 subtests passed`; `SECURITY_GATE=PASS`; compile/diff checks PASS. No live provider call or Credit mutation occurred.
- Slice D is engineering-complete; evidence: `docs/GOAL54_PRODUCTION_SLICE_D_EVIDENCE.md`.
- Locked-preview Owner review is now SHA-bound and provider-free; acceptance moves to explicit `KEEP_REQUIRED`, rejection to explicit `PREVIEW_REJECTED`.
- Keep/Kill consequence intent is persisted before provider mutation; ambiguous Keep/Kill outcomes fail closed and cannot auto-retry.
- A confirmed Keep followed by local output-acquisition failure recovers acquisition-only and cannot spend a second time; only validated, duration-checked, hash-bound clean output becomes `selected_asset`.
- Slice D broader regression: `85 passed, 2 subtests passed`; `SECURITY_GATE=PASS`; full hermetic regression: `761 passed, 283 subtests passed`.
- No live provider call or Credit mutation occurred. Elyum remains production-disabled.
- Slice E is engineering-complete; evidence: `docs/GOAL54_PRODUCTION_SLICE_E_EVIDENCE.md`.
- The ordinary project workspace now projects configured Full Video provider truth, routing state, durable provider-job presence, preflight/budget evidence, exact locked-preview SHA and safe continuation semantics from canonical artifacts only.
- The production reconciler now understands Elyum same-job resume, same-clientRef reconciliation, preview review, Keep/Kill, clean-output acquisition and ambiguous consequence states without falling through Flow recovery semantics.
- Accept/Reject remain provider-free review decisions; Keep and Kill remain separate explicit consequence confirmations. Clean-output reacquisition after confirmed Keep is acquisition-only and cannot call Keep a second time.
- Slice E focused UI/product gate: `22 passed`; application regression: `18 passed, 2 subtests passed`; broader regression: `99 passed, 2 subtests passed`; `SECURITY_GATE=PASS`; full hermetic regression: `765 passed, 283 subtests passed`.
- No live provider call or Credit mutation occurred in Slice E. Elyum remains production-disabled.
- Slice F engineering/UAT harness is now qualified; evidence: `docs/GOAL54_PRODUCTION_SLICE_F_EVIDENCE.md`.
- Offline two-shot production UAT covers fresh dispatch, same-job reload/resume, insufficient-credit fail-closed, exact continuity handoff, manual reject -> explicit Kill -> separately authorized replacement, explicit Keep, clean-output provenance, final render and idempotent rerender through canonical production services.
- Slice F verification: focused `29 passed`; broader `120 passed, 2 subtests passed`; full hermetic `767 passed, 283 subtests passed`; `SECURITY_GATE=PASS`.
- Fresh read-only Elyum preflight: slot 1 balance 30, slot 2 balance 110, quote 44 Credits for the qualified 4s/480p request. No provider mutation occurred in preflight.
- Bounded live production probe has now crossed the production adapter exactly once from source baseline `8b4e34fb7ea61dd80181e28fb25334880b5ec8a5`: one attempt, one provider submission, durable job `cos_leYmn4yuIWZosURXvTRbUo:a1056a5a-f249-4695-8a5e-93eb048ccdd5`.
- The first live wait ended `WAIT_UNAVAILABLE`; a separate local invocation resumed only that same job and reached `PREVIEW_READY` without upload/create redispatch.
- Live locked preview SHA-256: `a8c72a65008492638863ccfa31e0e59267e756c6d1d68a538883c0149e92a0f8`; contact sheet SHA-256: `8cfa8716c1602ba2a7de8b360684d8d8db819661f619eab8bb2d544cb96e9d91`; H.264 836x480, 24 fps, 4.041667 s.
- Provider reports `unlock_credits=20`. Post-preview read-only preflight: slot 1 balance 30, slot 2 balance 90, quote 44. No Keep/Kill has run.
- Exact locked preview was opened locally and Owner-rejected for stiff motion and facial expression. Canonical live state is `PREVIEW_REJECTED`; no Keep/unlock and no Kill has run.
- Root cause: the V1 prompt over-constrained movement (`almost locked`, `mostly steady`, tiny hand motion, subtle blink only) and named historical X2 despite the production continuity snapshot being bound to the supplied X3 frame.
- Correction SoT: `docs/GOAL54_LIVE_UAT_MOTION_ACTING_CORRECTION_V1.md`. Replacement attempts now support immutable `replacement_prompt` + SHA-256 + distinct clientRef provenance, and the UI exposes the full revised prompt before authorization.
- Ordinary Elyum routing remains disabled. Next consequence boundary is explicit Kill of the rejected preview, then a separately authorized one-attempt V2 replacement behind a fresh balance/quote preflight.

## Hybrid Visual / Opening Builder — accepted product direction (2026-09-15)

- This is a new feature track and is **not part of Goal 54**. Implementation has not started.
- Product decision SoT: `docs/decisions/0004-hybrid-visual-opening-builder.md`.
- Research baseline: `docs/HYBRID_VISUAL_RESEARCH_V1.md`.
- Keep Full Image and Full Video AI as separate modes; add a distinct `Hybrid Visual` mode.
- Narration/audio remains the canonical timeline. Subtitles and waveform run continuously across all visual-source changes.
- Opening Builder target is approximately **15–20 seconds**, normally decomposed into stable 5–10 second slots. Each slot receives an exact prompt/continuity snapshot and durable slot ID.
- Manual external generation is first-class: user copies one/all opening prompts, generates clips outside Story Auto, then imports each clip back into the exact slot. Slot binding, not filename guessing, is authoritative.
- API generation is an alternate acquisition path for the same opening slots; manual/API clips converge on the same normalized asset contract.
- Imported visual clips are probed, normalized and SHA-bound; embedded clip audio is ignored by default so Story Auto master narration/BGM/subtitle/waveform remain authoritative.
- After the opening, V1 mixes still-image blocks (restrained Ken Burns/pan/zoom/crossfade) with semantically relevant stock-video blocks. Do not use globally random stock.
- Pexels is the proposed first stock provider. Current official endpoint/restrictions/rate-limit/attribution findings are recorded in the research doc; selection must be relevance-filtered, deterministic, cached and provenance-bound.
- V1 intentionally does **not** insert AI video repeatedly throughout the body. Mid-body AI-video slots are deferred until the Hybrid Visual slot/import/compositor path is stable.
- Recommended sequence: H1 slot/planner contract -> H2 manual Opening Builder -> H3 optional opening API -> H4 Pexels body slots -> H5 full mixed compositor/UAT.
- Next implementation should begin with H1/H2 and prove a complete provider-independent manual opening round-trip before adding new paid/provider-dependent paths.

### Hybrid Visual H1/H2 checkpoint (2026-09-16)

- H1/H2 engineering is complete while `hybrid_hook` remains release-disabled (`FEATURE_NOT_AVAILABLE`); evidence: `docs/HYBRID_VISUAL_H1_H2_EVIDENCE.md`.
- Canonical `output/opening_manifest.json` now owns 15–20 second opening plans as 2–4 stable `OPENING_O*` slots of 5–10 seconds with exact prompt/context hashes and render-target snapshot.
- Manual external generation is implemented as exact-slot import, not filename guessing: FFprobe validation -> durable source copy -> FFmpeg normalization -> embedded-audio stripping -> source/normalized SHA binding.
- Materially short clips fail closed; small duration mismatch is repaired locally within a bounded tolerance. Longer clips are trimmed to the slot duration.
- Replacing one opening slot preserves prior asset provenance in slot-local replacement history and cannot silently rewrite other slots or the opening plan.
- Workspace/UI exposes shared continuity, exact prompt copy, copy-all prompt pack, per-slot import/replace, normalized preview, and readiness for existing/development `hybrid_hook` projects without bypassing the release guard.
- Targeted Opening Builder: 7/7 PASS, including canonical generation-request -> manual prompt-slot materialization with request identity and continuity context. Regression: Full Image 7 + Render 19 + Application 18 + Goal54 surface 4 = 48 PASS. Python compile and JavaScript syntax gates PASS.
- Python runtime dependencies lost after SSD migration were restored from repo `requirements.txt`; no Playwright browser install was performed.
- Next product slice is H3/H4 only after this checkpoint is durable: optional opening API acquisition using the same slots, then semantic Pexels body slots. Do not release-enable Hybrid Visual merely because H1/H2 backend/UI exists.

### Hybrid Visual H4 semantic stock checkpoint (2026-09-16)

- H4 engineering is complete while `hybrid_hook` remains release-disabled; evidence: `docs/HYBRID_VISUAL_H4_PEXELS_EVIDENCE.md`.
- Pexels official docs were rechecked before implementation; endpoint/auth/search options/default limits/rate-limit headers/24h cache guidance/attribution requirements are updated in `docs/HYBRID_VISUAL_RESEARCH_V1.md`.
- `output/hybrid_body_plan.json` now deterministically covers the narration timeline after the Opening Builder with repeating image blocks + bounded 5–10s STOCK_VIDEO slots and exact no-gap/no-overlap timing.
- Stock queries derive from overlapping narration semantics; Pexels is never sampled globally/randomly. Every stock slot has explicit IMAGE fallback.
- Pexels search response caching, rate-limit observability, creator/source attribution, deterministic top-relevant selection and same-project duplicate avoidance are implemented without persisting the API key.
- One-stock-slot acquisition is `cached search -> durable selection -> bounded Pexels-domain download -> FFmpeg silent normalization -> SHA-bound local asset`; READY slots are idempotent and do not re-search/download on rerender.
- Development workspace exposes body recipe/stock query/status plus Pexels attribution/link, but release availability remains `FEATURE_NOT_AVAILABLE`.
- H4 targeted tests: 7/7 PASS using mocked API/network plus real FFmpeg normalization. No live Pexels request occurred.
- H3 opening-API acquisition remains optional/deferred because manual opening is already Product Acceptance-capable at the slot level; it must reuse the H1/H2 slot contract rather than fork it.
- Next required product slice is H5 mixed compositor + exact E2E UAT. Hybrid Visual must not be release-enabled before H5 proves opening -> images/effects -> stock -> images with narration/subtitle/waveform continuous from t=0 to final.

### Hybrid Visual H5 mixed compositor checkpoint (2026-09-16)

- H5 provider-free mixed preview foundation is implemented; evidence: `docs/HYBRID_VISUAL_H5_MIXED_COMPOSITOR_EVIDENCE.md`.
- Body IMAGE slots now accept explicit local images with durable SHA binding/replacement history; STOCK_VIDEO slots can carry an explicit image fallback without changing their semantic slot identity.
- Preview readiness fails closed until Opening Builder is READY, every body IMAGE has an image, and every stock slot has either a normalized stock video or image fallback.
- `render_hybrid_preview(...)` composes Opening Builder + image motion + stock/fallback + image motion on the exact alignment master clock, then delegates narration/subtitles/waveform/BGM to the existing Story Auto compositor.
- Every visual source is silent by contract; opening/stock clips with embedded source audio are rejected unless their normalized local asset has already stripped audio.
- Development artifacts are `output/hybrid_preview.mp4` + manifest/subtitles only; H5 deliberately does not write `output/final.mp4` and does not release-enable `hybrid_hook`.
- H5 focused real-FFmpeg suite: 2/2 PASS. Synthetic 36s proof includes source changes `OPENING_VIDEO -> IMAGE -> STOCK_VIDEO -> IMAGE`, exact slot continuity, one final master audio stream, canonical narration SHA, subtitles and waveform.
- UI now supports body image/fallback import and a readiness-gated `Render mixed preview` action for existing/development Hybrid projects.
- Remaining gate is one owner-visible exact E2E UAT on representative content, then any UX/quality corrections, Product Acceptance, final-render promotion and only afterward release activation.
- H3 opening API acquisition remains optional and must reuse the H1/H2 slots if implemented; it is not required to validate the manual low-cost Hybrid V1 journey.
- Real-asset H5 local UAT now PASSes machine checks via `tools/hybrid_visual_uat.py`: Xianxia kept-clean opening assets + real anchor/continuity images -> 42.583333s mixed preview, SHA-256 `7aa58eee8a40dfa014d082cdc6bc297f506ae1627b4cd99c314de791f78851dd`, exact source order `OPENING_VIDEO×2 -> IMAGE×3 -> STOCK_IMAGE_FALLBACK -> IMAGE`, waveform enabled, visual audio muted. Runtime evidence is under `../evidence/hybrid_visual_h5_uat/`.
- The same UAT workspace projection truthfully remains `FEATURE_NOT_AVAILABLE` while reporting opening/body/preview READY; release activation is therefore still fenced correctly.
- Superseded by Owner priority 2026-09-18: visual/aesthetic acceptance is deferred and is no longer the next blocker. Keep technical integrity/provenance gates, but prioritize correct format contract, reliable pipeline/recovery and a smooth canonical CUJ.
- Post-SSD Kokoro probe currently reports `KOKORO_MODEL_NOT_FOUND`; UAT used Windows Zira locally so this independent environment drift did not contaminate H5 qualification.

### Hybrid Visual canonical CUJ / Product Flow Acceptance (2026-09-16)

- Decision SoT: `docs/decisions/0005-product-journey-and-hybrid-flow-acceptance.md`; evidence: `docs/HYBRID_VISUAL_CUJ_FLOW_ACCEPTANCE.md`.
- Acceptance is deliberately split: **`PRODUCT_FLOW_ACCEPTED / QUALITY_DEFERRED`**. Product Journey/CUJ is not the same thing as the internal Execution Pipeline, and technical pipeline PASS alone is not product acceptance.
- Hybrid now uses the canonical six outer stages `SOURCE -> TIMING -> PLAN -> VISUALS -> QUALITY -> RENDER`; there is no second Hybrid production pipeline.
- New-video UI exposes `HYBRID VISUAL`; UI-created Hybrid projects snapshot `hybrid_visual.cuj_enabled=true`. Historical Hybrid projects without this explicit flag remain `FEATURE_NOT_AVAILABLE`. Full Image remains the default.
- PLAN prepares canonical story approval plus a 15–20s Opening Builder and Hybrid body plan. Manual opening generation/import remains first-class.
- VISUALS reuses the existing Flow image engine for body IMAGE slots. Semantic Pexels stock remains optional for flow completion; stock slots can automatically use generated-image fallback.
- QUALITY is `TECHNICAL_ONLY_V1` for this acceptance. It proves integrity/binding, not motion/aesthetic quality.
- RENDER promotes the mixed compositor to canonical `output/final.mp4` + `output/final_manifest.json`; narration/subtitles/waveform remain master tracks and visual audio stays muted.
- Stale-state test proves replacing an Opening asset after final moves the project back to QUALITY and removes RENDER COMPLETE authority.
- Browser gates PASS: New video exposes/selects Hybrid Visual; prepared project performs opening import -> Continue -> COMPLETE -> Open final video.
- Post-promotion qualification: **76 tests PASS**, Python/JS syntax PASS, `SECURITY_GATE=PASS`, `YOUTUBE_AUTO_RUNTIME_IMPORTS=0`.
- Hybrid Quality V2 remains a deferred backlog track (motion/effects, stock relevance, transitions, pacing, subtitle/waveform styling). Owner priority from 2026-09-18 is to **skip further quality optimization for now** and focus active work on correct output format, pipeline correctness/recovery and CUJ smoothness. Do not reopen the accepted CUJ merely because output quality is not yet optimized.

### Owner delivery priority — Format + Pipeline + CUJ (2026-09-18)

- Owner directive: **skip further visual/aesthetic quality work for now; improve it later**.
- Visual quality remains explicitly `QUALITY_DEFERRED` and must not block the current delivery path.
- Active product goal is now: **correct format + correct/recoverable pipeline + smooth CUJ**.
- Correct format means each selected mode produces its canonical artifact/media contract with master narration/subtitle/waveform ownership preserved and technically valid duration/streams.
- Pipeline acceptance focuses on deterministic stage progression, no duplicate/ambiguous provider effects, safe resume/recovery, stale-state invalidation, fallback behavior, and canonical final-output promotion.
- CUJ acceptance focuses on one coherent user journey: clear current state, visible action result/progress, obvious next action, no dead-end or hidden backend wait, resume without redoing completed work, and safe repeat-run lifecycle after completion.
- This priority change does **not** waive security, provenance, media validity, fail-closed behavior, cost/consequence boundaries, or technical QUALITY checks.
- Deferred backlog includes motion/acting naturalness, aesthetic polish, stock relevance tuning, transition taste, pacing polish, and subtitle/waveform styling.
- QV2-A engineering evidence already landed (mixed CUT/CROSSFADE + deterministic anti-loop motion grammar) and may remain as-is; no further quality tuning is required before continuing CUJ/pipeline work.
- Product HEAD after QV2-A: `001253f0924d025b3903657064ea5b17c6dc314e`; runtime Xianxia Hybrid UAT PASS at 42.583333 s. This proves technical renderability only, not visual-quality acceptance.
- Decision policy is updated in `docs/decisions/0005-product-journey-and-hybrid-flow-acceptance.md`.

### CUJ completion / repeat-use checkpoint (2026-09-18)

- Audit found a real COMPLETE-screen defect: `Render again` had two click handlers and could attempt the same rerender command twice from one owner click. The duplicate binding is removed; one click now owns one rerender action.
- COMPLETE now exposes an explicit `Create another video` CTA that returns directly to the canonical New Video wizard, so repeat daily use does not dead-end at the finished artifact.
- User-visible mojibake on project/status/provider/wizard surfaces was repaired; the UI regression now rejects common mojibake markers.
- Narration word-count regex was repaired from an encoding-corrupted character class to Unicode `\w` plus apostrophe/hyphen, preserving multilingual duration estimates without junk codepoints.
- Verification: `tests.test_ui + tests.test_application` = 26 tests PASS (2 environment-specific system-Chrome browser tests skipped); Hybrid canonical CUJ = 4/4 PASS including Playwright `New video -> Hybrid Visual` and `Import opening -> Continue -> COMPLETE -> Open final video`; JavaScript syntax and `git diff --check` PASS.
- No provider, render-format, quality-policy, or generation semantics changed in this slice.

### Hybrid Visual provider-configuration checkpoint (2026-09-16)

- Pexels credential UX is product-complete without making Pexels a hard dependency; evidence: `docs/HYBRID_VISUAL_PROVIDER_SETUP_EVIDENCE.md`.
- Settings supports Save / Test connection / Remove for Pexels. Saved credentials use the existing Windows DPAPI Story Auto credential store and are never persisted in project/repo artifacts.
- New Video Hybrid projects project Pexels readiness before creation; missing Pexels explicitly uses generated-image fallback and does not block Run-to-Final.
- Provider setup targeted verification: 3/3 PASS; existing H4 Pexels suite: 7/7 PASS; no real Pexels request occurred during qualification.
- Remaining provider-configuration gap is H3 optional Opening API acquisition. Manual Opening Builder remains the accepted fallback and must stay available even when no video API credential is configured.

### Hybrid Visual H3 Opening API checkpoint (2026-09-16)

- Optional BytePlus Seedance T2V acquisition now reuses the canonical Opening Builder slots; manual external generation/import remains first-class.
- `Run/Continue` never auto-spends on Opening API. The owner explicitly chooses `Generate with API` per exact slot.
- BytePlus credentials use the shared Story Auto DPAPI credential boundary with Settings Save/Test/Remove and environment override support.
- Provider intent is persisted before POST; known task IDs resume without new POST; ambiguous POST is never blindly redispatched.
- Success downloads and normalizes through the same silent SHA-bound opening import contract used by manual clips.
- Evidence: `docs/HYBRID_VISUAL_H3_OPENING_API_EVIDENCE.md`. Targeted H3 suite: 5/5 PASS with mocked provider transport and browser UI; no live provider spend.
- Provider Configuration Journey is now complete for Hybrid V1: Opening manual/API + Pexels configured/fallback. Quality remains deferred.

### Capability-first video provider registry checkpoint (2026-09-16)

- CADS current HEAD `62cf2aa` was verified aligned with remote before this architecture change.
- Decision SoT: `docs/decisions/0006-capability-first-video-provider-boundary.md`; evidence: `docs/VIDEO_PROVIDER_REGISTRY_EVIDENCE.md`.
- `Seedance` is now modeled as a capability/model family independent of provider identity.
- Canonical catalog: BytePlus Tier A/direct API; Elyum Tier A/MCP candidate; Dola Tier B/experimental session; Manual external Tier C/always available.
- Cross-provider fallback is allowed only before dispatch/effect ambiguity; ambiguous or confirmed effects must reconcile the same provider identity first.
- Settings exposes the registry read-only. Existing generation routing is intentionally unchanged in this slice.
- Next bounded slice: promote Elyum credential/readiness + explicit Opening Preview/Keep/Kill path; Dola remains experimental.

### Hybrid Visual Elyum Opening engineering candidate (2026-09-16)

- Provider registry checkpoint `f5254f3` remains authoritative for capability-first routing and pre-dispatch-only provider switching.
- Elyum Hybrid Opening adapter now has engineering coverage for T2V preflight, deterministic clientRef replay, locked preview review, explicit Keep/Kill consequence boundaries, successful bind into the canonical Opening slot, manual fallback, and cost no-dispatch.
- Elyum credentials reuse Story Auto Windows DPAPI + environment override and Settings Save/Test/Remove; Test is read-only.
- Evidence: `docs/HYBRID_VISUAL_ELYUM_OPENING_CANDIDATE_EVIDENCE.md`. Backend consequence lifecycle + browser product surface are covered; DPAPI fake-key round-trip remains PASS.
- Status: **PRODUCT_SURFACE_WIRED / LIVE_PROVIDER_GATED**. Hybrid Opening now exposes Elyum per-slot preflight, model/cost choice, locked-preview review, explicit Keep spend, explicit Kill release, and same-request reconciliation. Manual import remains available whenever no unresolved provider consequence exists.
- Product-surface qualification: 55 relevant tests PASS, including browser state visibility; Python/JS syntax PASS and `SECURITY_GATE=PASS`. No live provider generation/Keep/Kill or credit spend occurred in this qualification.

### Dola provider contract research (2026-09-17)

- Research SoT: `docs/DOLA_PROVIDER_RESEARCH_2026-09-17.md`.
- Dola currently exposes Seedance 2.5 browser generation with short 4–15s clips and free/paid credits, but no stable provider-authored developer API contract was found in the accepted research surface.
- Public Dola Terms prohibit reverse engineering. The known cookie client explicitly reverse-engineers Android/web-session behavior, so Story Auto will **not** implement that private/internal route as a product adapter.
- Registry identity changed from `dola_session` to `dola_official`: experimental, `OFFICIAL_API_CONTRACT_NOT_QUALIFIED`, not production-routed.
- Until an official supported API is qualified, Dola remains available through the existing Manual external generation → Import clip journey.

### Hybrid Opening provider policy (2026-09-17)

- New Hybrid projects persist `settings.hybrid_visual.opening_provider_policy` with one of `AUTO`, `BYTEPLUS`, `ELYUM`, or `MANUAL`; default is `AUTO`.
- `AUTO` means deterministic offer/readiness ordering only. It never dispatches generation, calls Elyum Keep/Kill, or spends credits automatically.
- Opening Builder reads the persisted project policy when no provider effect exists. Once a BytePlus/Elyum effect is submitted or ambiguous, recovery remains bound to that provider identity regardless of policy.
- Manual import remains available whenever no unresolved provider consequence exists.
- Server creation boundary normalizes the policy to uppercase and rejects unknown values with `HYBRID_OPENING_PROVIDER_POLICY_INVALID`; private/session-only provider identities cannot be smuggled through project settings.
- Qualification: 48 Hybrid/provider/application/release tests PASS, Python/JS syntax PASS, `SECURITY_GATE=PASS`, `git diff --check` PASS.

### Provider credential key-pool UX (2026-09-17)

- Decision SoT: `docs/decisions/0007-provider-key-pool-append-semantics.md`.
- Root cause closed: Settings previously called the pool setter with one key, replacing all previously saved keys even though the credential boundary was already pool-based.
- Implemented behavior: multiline batch input, atomic validation, append + stable-order dedupe, saved-key count only, no secret projection, and remove-all for the saved DPAPI pool.
- Scope: BytePlus, Elyum, and Pexels Settings credential UX. Existing environment override semantics and provider execution routing remain unchanged.
- Acceptance evidence: batch append preserves old keys, duplicates are idempotent, invalid batches do not mutate, browser Settings proves saved-key count grows 2 -> 3 without rendering secrets, legacy single-key route remains compatible.
- Qualification: 48 provider/application/release tests PASS; focused credential/browser suite 9/9 PASS; Python/JS syntax PASS; `SECURITY_GATE=PASS`; `git diff --check` PASS.

### AI brain upgrade: Gemini 3.8 + external Anthropic-compatible gateway (2026-09-17)

- Decision SoT: `docs/decisions/0008-gemini-3-8-and-external-llm-gateway.md`.
- Gemini HARD reasoning baseline is now `gemini-3.8-flash`, followed by 3.7, 3.6, 3.5, then established 2.5 fallbacks. New Gemini projects default to 3.8; existing project bindings remain immutable.
- Added generic `external_anthropic` brain provider rather than a reseller-specific adapter. Contract: Anthropic Messages `/v1/messages`, configurable HTTPS base URL/path prefix, model alias, `x-api-key` or Bearer auth, append-only DPAPI key pool, live Test connection.
- External model names are treated as gateway aliases; provenance records configured alias + gateway-reported model without claiming upstream vendor identity.
- Settings journey supports Use Gemini 3.8, configure external gateway, add multiple keys, Test connection, remove saved keys, and switch back to Gemini. Brain defaults apply only to new projects.
- Safety: non-loopback HTTP, URL credentials, query/fragment URLs and path traversal fail closed; secrets never enter project/runtime-default JSON or Settings responses.
- A named reseller such as ETFBit is not considered production-qualified until its actual API base URL + model alias pass Story Auto's live Test connection. The shop/account URL is not used as an API endpoint.
