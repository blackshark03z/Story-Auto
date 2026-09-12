# Goal 54 — Full Video Seedance Provider Qualification

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
Technical acquisition/provenance is verified; human visual rubric and explicit
Keep/Kill remain unresolved, so X1 is not yet accepted.
