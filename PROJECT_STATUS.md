# Project Status

## Current accepted state

**V1.0.0_STABLE / POST_RELEASE_GOALS_10_11_12_ACCEPTED / GOALS_13_14_15_16_17_LOCAL_CANDIDATES**

Frozen product design: Story Auto V1, 2026-08-12.

The stable release baseline is **Story Auto v1.0.0 Stable**, release commit
`6dc3188a16bd1ae4f84906f891083ec6c0651154`, annotated tag `v1.0.0`.
That release evidence remains historical and immutable.

The current accepted post-release development state includes:

- **Goal 10** (`STORY-AUTO-GOAL-10-UX-UI-SIMPLIFICATION`), accepted at
  `b132c8c38fa3cd2041282df8d6109a8efe9d0992`: the creator workflow is
  `CONTENT → SETUP → CREATE → REVIEW → DONE` across Home, Project, and
  Settings, with Advanced and Diagnostics secondary. Product core behavior did
  not change.
- **Goal 11** (`STORY-AUTO-GOAL-11-FLOW-IMAGE-MARK-POSTPROCESSING`), accepted
  at `3d4e2a423d806f3feb091d1076bda901fc8b43d1`: production Flow images retain
  immutable raw provider evidence, then use a deterministic locally cleaned,
  validated derivative as `selected_asset`. Flow video retains its accepted
  visible-provider-mark limitation. Focused tests passed 34/34, the full
  offline suite passed 141/141, quality and security gates passed, and the
  24-item visual corpus passed.
- **Goal 12** (`STORY-AUTO-GOAL-12-STATE-SYNC-AND-GIT-PUBLISH`), accepted at
  `61659579c3f288b9b27b3581f2c981162eff6919`: repository and Build OS state
  are synchronized with `origin/main` at that commit.
- **Goal 13** (`STORY-AUTO-GOAL-13-AMBIENT-STORY-FOUNDATION`) is a local
  post-release candidate. It adds the Ambient Story capability and offline
  engineering demos without advancing the accepted remote baseline; real Quiet
  Verdict and Hidden Mastery production trials remain the next product gate.
- **Goal 14** (`STORY-AUTO-GOAL-14-KOKORO-READINESS-AND-MODEL-RECOVERY`) is the
  narrow corrective candidate discovered by the first Quiet Verdict trial.
  Kokoro readiness now uses one offline load authority for Settings and
  production, requires the configured model snapshot and selected voice, and
  fails before Gemini or Flow when local TTS is unavailable. The trial project
  remains preserved for a separate UI resume after corrective validation. The
  observed imported-package title metadata carryover issue is explicitly
  deferred to later UX corrective work.
- **Goal 15** (`STORY-AUTO-GOAL-15-AMBIENT-VISUAL-PLANNING-AND-PROMPT-BOUNDS`)
  corrects Trial A's visual-only defects: semantic compatibility now outranks
  preferred image count, narration summaries are separate from concise visual
  anchors, Flow IMAGE prompts compile within a centralized bound, and Review
  cannot claim a visual match before selected generated evidence exists. Trial
  A's content, Kokoro narration, and alignment remain the resume authority;
  Trial B has not begun.
- **Goal 16** (`STORY-AUTO-GOAL-16-FLOW-IMAGE-DISPATCH-ACK-RECOVERY`) is the
  narrow Flow corrective candidate that separates a trusted Flow dispatch
  confirmation from a generic UI acknowledgement and preserves an uncertain
  attempt rather than blindly submitting again.
- **Goal 17** (`STORY-AUTO-GOAL-17-FLOW-QUEUE-BARRIER-AND-ASSET-ATTRIBUTION`),
  source implementation anchor `74b1ff6dfdb33811daa4abb731888452a0e70628`,
  adds the project-wide serial Flow queue barrier and request-epoch output
  attribution. A confirmed dispatch is not a confirmed asset: a
  `selected_asset` is permitted only after one stable, request-specific
  provider lineage is confirmed. Stale/foreign output, gallery recency, and
  timestamp proximity are not ownership evidence; competing candidates remain
  ambiguous. Goal 17 acceptance preserved Trial A and did not execute Trial B.

The current source implementation anchor is Goal 17; resolve live `HEAD` for
the documentation-sync commit rather than treating this current-state record as
a self-pinning Git authority.

## Trial A and next-techlead handoff

Trial A remains the preserved Quiet Verdict project
`prj_4f895eb1436c42c4ba5b908381b14fd1`; it is not a replacement-project or
fresh-batch candidate. Its current manifest has 14 IMAGE requests. The first
unresolved request, `req_28728acbcab5522b8685`, is `AMBIGUOUS` with
`FLOW_DISPATCH_UNCERTAIN`: its first attempt was reconciled as
`NOT_DISPATCHED`, while its second reconciliation remains `AMBIGUOUS`.
`req_6b755dde5a6e7b5c3295` has the same unresolved dispatch state.
`req_3591b82710f9c1c59acf` is `FAILED_RETRYABLE` with
`OUTPUT_ATTRIBUTION_INVALID`: its formerly successful, dispatch-confirmed
attempt has invalidated attribution and no selected asset. These states are
preserved evidence, not a license to resubmit or to select an
available-looking gallery item; the listed unresolved requests have no
`selected_asset`.

The safe next action is for the next techlead to resume this existing project
only through the Goal 17 reconciliation/barrier path. It must reconcile the
earliest unresolved attempt before any Flow activation. If that reconciliation
does not prove a safe resolution, the serial project queue remains halted; do
not click Generate, select newest output, use timestamps as ownership evidence,
or begin Trial B. Only a confirmed request-specific attribution (or the
supported manual recovery/retry outcome after reconciliation) can release the
barrier for the next activation.

## Accepted feature inventory

- Primary input: `content.md` with strict `## Narration`.
- Formats: `hybrid_hook`, `full_video_ai`, and local-candidate `ambient_story`.
- Ambient styles: `quiet_verdict`, `hidden_mastery`.
- TTS: ElevenLabs + Typecast + explicitly selected Kokoro Local.
- Kokoro Local `Ready` requires its configured runtime, exact local model
  snapshot, selected voice, and load-only initialization probe to pass.
- Planning LLM: Gemini 3.5 Flash baseline; 3.6 Flash benchmark candidate.
- Visual provider: Google Flow for images/video.
- Canonical alignment timing.
- Story timeline / continuity / shots / media separation.
- Human approval gates before large generation batches.
- Per-request manifest, retry, resume, and explicit provider errors.
- Normalized silent-MP4 media boundary before common composition.
- Narration/subtitles + optional local/licensed BGM.
- 1080p 16:9 MP4 output with raw asset retention.
- Title/description/thumbnail package.
- CLI first; local UI after hybrid pipeline proof.

## Accepted implementation evidence

- Strict `content.md` parsing requires exactly one non-empty `## Narration`
  section; arbitrary document body is not treated as narration.
- Durable JSON/text artifact publication is atomic and UTF-8.
- Direct stage inputs have deterministic canonical SHA-256 fingerprints.
- Focused offline tests cover valid/invalid narration input, failed atomic
  replacement preservation, and fingerprint determinism.
- Runtime roots are isolated into Story Auto-owned projects, Flow browser
  profile, cache, temp, logs, evidence, and locks directories.
- Opaque project IDs and durable project-relative artifact paths reject
  absolute or escaping paths.
- Versioned minimal project contracts validate render mode and isolate each
  project into `project.json`, `content.md`, `output/`, and `logs/`.
- Project locks are one-writer-per-project with conservative stale recovery.
- The `content` pipeline stage produces a deterministic `content_manifest.json`
  with atomic checkpoint RUN/SKIP/invalidation behavior.
- The CLI supports project creation, run, and resume entirely offline.
- Gemini planning is isolated behind a Story Auto provider boundary with
  credential sanitization, structured-output validation, bounded retry, and an
  explicit capability probe.
- `story_timeline.json` resolves model grouping to canonical alignment segments;
  it never accepts model-generated timestamps as timing authority.
- `continuity_bible.json` retains stable typed entity IDs and separates narrated
  facts from generated visual-design choices. Planning artifacts include safe
  request provenance and are atomically published only after validation.
- Planning checkpoint identities skip unchanged timeline/continuity artifacts,
  rerun missing/corrupt continuity independently, and invalidate downstream
  continuity when timeline semantics, prompt version, or model changes.
- A validated plan is not approved. `approve-plan` writes hash-bound durable
  `review_state.json` approval after semantic validation.
- Visual planning now compiles independent shot, media, and generation-request
  artifacts. Shot IDs, reference dependencies, request fingerprints, hybrid
  hook boundaries, full-video constraints, media overrides, and attempt
  exposure are validated before any provider execution is possible.
- `plan-visuals` creates those artifacts; `approve-shot-plan` records the
  required hash-bound human planning approval. Neither command calls Flow.
- One bounded Gemini 3.5 fixture passed timeline/continuity/shot planning and
  both hybrid and full-video media/request compilation; the runtime evidence
  records aggregate usage and latency only.
- Goal 05 lifecycle validation is bound to the accepted planning implementation
  commit and its offline/live evidence.
- The Flow provider foundation now owns a separate runtime profile path,
  CDP-backed Flow page/session adapter, explicit isolated-profile launcher,
  capability preflight, fail-closed composer page object, append-only
  `generation_manifest.json`, dependency-aware explicit execution gate, and
  atomic local image/video asset selection. Offline fixtures prove selector
  ambiguity rejection, auth/project capability results, resume reuse, invalid
  selected-asset invalidation, and no blind post-timeout resubmission.
- Flow execution is now a serial manifest queue: any generating,
  dispatch-uncertain, attribution-uncertain, or attribution-ambiguous attempt
  blocks every later Flow activation across CLI, UI, batch, retry, and resume.
  Reconciliation runs on the earliest unresolved attempt first. A stable
  pre-dispatch provider baseline plus a request-specific provider delta is
  required for attribution; stale or foreign output is excluded, multiple
  unlineaged candidates remain ambiguous, and no newest/timestamp heuristic
  can create ownership. Dispatch confirmation and asset attribution are
  independently recorded, and postprocess/`selected_asset` require confirmed
  attribution.
- Live Flow image/video execution, reference attachment, local acquisition,
  append-only attempt provenance, ambiguous-result reconciliation, and unchanged
  provider resume are accepted with real Story Auto assets.
- Bounded live Gemini fixture validation passed for `gemini-3.5-flash`; the
  identical `gemini-3.6-flash` benchmark was available and passed without
  changing the production baseline. Safe metrics are in runtime evidence.
- `render_plan.json` resolves exact validated local sources and fails closed for
  missing required video. Preferred hybrid fallback is explicit and inspectable.
- FFmpeg/FFprobe helpers normalize IMAGE (STATIC/SLOW_PUSH/SLOW_PAN), 720p VIDEO,
  and HOLD sources into deterministic silent scene MP4s. The common compositor
  owns crossfades, canonical-duration accounting, subtitle burn-in, narration,
  optional local BGM, final validation, and atomic publication.
- Render checkpoints isolate render-plan, per-shot clip, subtitle, audio-plan,
  final-render, publishing-metadata, and thumbnail dependencies. Real recovery
  cases prove render-only recovery, one-clip recovery, selected-asset
  invalidation/reconciliation, and zero-work unchanged resume.
- Gemini title/description generation and Flow thumbnail generation publish a
  project-bound `publishing_package.json`; visually rejected provider candidates
  remain append-only provenance and cannot become the selected thumbnail.
- Structured `NATURAL_SOFT_REALISM` policy now compiles image intent separately
  from motion-only reference-video prompts; generic AI-polish defaults are not injected.
- Production media uses `IMAGE output_count=1` and pauses at naturalness QC.
  For Flow IMAGE, raw provider bytes are immutable evidence and a deterministic
  local postprocess creates the separately hashed clean derivative selected for
  downstream use; a remaining visible provider mark fails QC. Flow VIDEO is
  unchanged and retains the visible-provider-mark limitation accepted in V1.
- `full_video_ai` now partitions long shots into deterministic video request
  parts, supports explicit repeated-kind production batches, and renders only
  complete all-video coverage through the common compositor.
- Optional `NATURAL_SOFT` normalization applies restrained saturation/contrast,
  highlight, and fine-grain finishing without blur or sharpening.
- A loopback-only local operator dashboard now covers project/content status,
  planning, references, shots, prompt edits, replacement/regeneration, production
  QC, safe generation controls, rendering, provenance, and publishing. CLI and UI
  mutations share `OperatorService` and the accepted core services.
- Goal 10 reorganizes that operator capability into Home,
  three-step New video, focused Project, Review, completion, and Settings
  surfaces. Human status, progress, and one next action lead; raw IDs, paths,
  manifests, provider attempts, and low-level controls are disclosed only under
  Advanced or Diagnostics. Owner visual and experiential acceptance is complete.
- Goal 11 supports the verified Flow image profiles `1280x720 v1` and
  `1376x768 v1`; unsupported image geometry fails closed locally. A missing,
  corrupt, or failed clean derivative is rebuilt from valid raw evidence and
  must not cause a new Flow submission solely for postprocessing recovery.
- Ambient visual planning uses the existing shot/media/request/render artifacts
  and a two-stage narrative-state → compatible-anchor policy. Quiet Verdict is
  preferred 2–5/hard maximum 8; Hidden Mastery is preferred 4–7/hard maximum
  10. Preferred overflow requires `SEMANTIC_STATE_INCOMPATIBILITY`. Visual
  anchors and broad narration summaries are separate, and only bounded visual
  intent reaches Flow IMAGE compilation (1,100 internal target, centralized
  1,200 hard limit, no blind truncation). Ambient remains `IMAGE / REQUIRED`
  with temporal video QC `NOT_APPLICABLE`; its six deterministic local motion
  primitives remain within 1–3% scale bounds with seeded subtle fine grain.
- Ambient style prompt changes invalidate visual-generation descendants while
  local motion/overlay enablement invalidates render descendants only. Existing
  `hybrid_hook` and `full_video_ai` policies remain separate.
- The normal New video flow exposes Format and contextual Ambient Style; raw
  motion, overlay, budget, FFmpeg, and QC controls remain absent from the normal
  surface and available only through resolved diagnostics artifacts.
- Release hardening adds pre-dispatch workspace-capacity checks, atomic
  normalized/final media publication, restart proofs for interrupted planning
  and acquisition, zero-byte/partial-media rejection, and a credential/signed-URL/
  runtime-import security gate.
- A 71.067-second real hybrid prototype and a 5.867-second technical
  representative production passed 1080p runtime/visual review. No approved
  long-form content exists in canonical local project/kit locations, recorded as
  `LONG_FORM_CONTENT_NOT_AVAILABLE` rather than inventing creative content.

## Configuration/schema authority

Normative V1 artifact semantics are in `docs/specs/ARTIFACT_CONTRACTS_V1.md` and `contracts/schemas/`. Secrets are never stored in project artifacts.

## Historical Goal 08 release decision and remaining dependency

- Production media routing is final: `GOOGLE_FLOW_WEB` for images and videos.
  Provider-selection research is `CLOSED_BY_OWNER_DECISION`; completed Flow,
  Gemini API, and Gemini Web evidence remains append-only provenance.
- At the v1.0.0 release, the Flow sparkle mark was an
  `ACCEPTED_KNOWN_LIMITATION` for both media types and was never removed,
  covered, masked, inpainted, or cropped away. Bottom-right prompt composition
  and right-cleared lower-third subtitles mitigate collision without distorting
  shots. Representative review found zero focal-subject, subtitle, or critical
  prop/text overlaps across 8 provider shots and 5 final-render frames.
- A representative approved long-form creative production. Exhaustive runtime
  inventory found only short fixtures and the repetitive 71.067-second technical
  fixture, so the durable terminal dependency is `LONG_FORM_CONTENT_REQUIRED`.

## Goal 08 production evidence

- The 71.067-second hybrid fixture rerendered under release code and passed
  technical H.264/AAC validation. It remains an engineering fixture because its
  scene and narration repeat, not because of the accepted Flow mark.
- Unchanged render resume skipped render plan, all ten normalized clips,
  subtitles, audio plan, and final composition without rewriting `final.mp4`.
- Removing only normalized `sh_0005` rebuilt exactly that clip and the final
  composite; all independent stages and the other nine clips skipped.
- `tools/goal08_production.py` creates a hash-bound, secret-free local summary at
  `runtime/evidence/goal08/goal08-production-summary.json` and never submits a
  provider or approves creative work.

## Goal 08 provider-quality provenance

- Live capability discovery found the current official model identities:
  `gemini-3.1-flash-image` (Nano Banana 2), `gemini-3-pro-image` (Nano Banana
  Pro), `gemini-omni-flash-preview`, and `veo-3.1-generate-preview`.
- The Gemini media and Gemini Web adapters and their partial evidence remain as
  historical benchmark provenance. Neither is a production route in V1.
- Actual execution is account-blocked: all 18 valid credentials in the isolated
  pool report zero Nano Banana 2 quota; three legacy pool entries are invalid or
  unauthenticated. Bounded Nano Banana Pro, Omni, and corrected Veo reference
  probes also reach the API but return zero-quota rate limits. No API media job
  or result was accepted.
- The closed anonymous review workspace is at
  `runtime/evidence/goal08/provider_benchmark/`. It contains the exact semantic
  fixtures, randomized reveal mapping, rubric, contact sheets, Flow baseline,
  and unavailable API attempt identities. It is not a completed benchmark and
  cannot support a provider recommendation.
- The only terminal dependency is `LONG_FORM_CONTENT_REQUIRED`. No approved
  canonical content at least 300 seconds long exists; Story Auto will not invent it.
