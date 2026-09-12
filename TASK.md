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
- First implementation candidate: BytePlus ModelArk first-party Seedance 2.5
  (`dreamina-seedance-2-5-260628`) through the official asynchronous contents
  generation API. Third-party API providers remain fallback research only until
  direct first-party runtime evidence proves or blocks this path.

## Progress

- Current CADS standard/template reviewed through the registered local CADS
  project.
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
- A zero-generation live preflight is implemented at
  `tools/goal54_seedance_preflight.py`.

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
  or `ARK_API_KEY`. This is the current direct Stage B blocker; it is not an
  engineering PASS or provider failure.

## Next Safe Action

Keep the BytePlus implementation and regressions green. Once a ModelArk API key
is configured in the Story Auto process, run the zero-cost list-tasks preflight;
if it passes, execute exactly one 4-second 480p Stage B fixture through Story
Auto, retain task/result/hash evidence, then prove manual acceptance and the
existing render contract. Do not fall back to a browser provider to bypass the
credential blocker.
