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

## Progress

- CADS refreshed from `origin/master` on 2026-09-12 at `432a19a`
  (`Strengthen project architecture description`). The frozen Standard/Five
  Controls remain unchanged; Story Auto now applies the new conditional
  Architecture Description rule for material provider/runtime/trust shape.
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
- Elyum Free developer/MCP read access is now proven by runtime preflight. No
  generation has been dispatched. The earlier five-test nominal Credit plan was
  invalidated by live estimates and is superseded by the bounded 120-Credit
  Fast-I2V -> 2.5-Reference plan in `GOAL54_SHOT_RECIPE_EXPERIMENT_V1.md`.

## Next Safe Action

Keep the BytePlus implementation and regressions green as the stable fallback.
Use `docs/GOAL54_SHOT_RECIPE_EXPERIMENT_V1.md` as the bounded cinematic research
contract. Implement one narrow research-only Elyum adapter around `elyum_upload`,
`elyum_estimate`, idempotent `elyum_make_video`, durable `jobId`, and same-job
`elyum_wait`; expose keep/kill explicitly but do not auto-call either. Do not
change product routing yet. Prepare one fixed character/reference fixture and
re-estimate immediately before R1. Do not dispatch generation until adapter/
recovery tests pass and the bounded 120-Credit experiment still fits the live
balance. BytePlus remains the stable production fallback; Pollo stays deferred
until its API wallet itself proves usable free credit.
