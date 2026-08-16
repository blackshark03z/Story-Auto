# Changelog

## 1.0.0 - 2026-08-14

- Freeze the accepted V1 feature set as Story Auto v1.0.0 Stable.
- Record Video 001 and Video 002 as canonical long-form production regressions
  with exact accepted-master hashes and durable evidence pointers.
- Document accepted provider/runtime behavior and the stable known limitations,
  including Flow watermark/UI/authentication constraints, Kokoro Local runtime
  dependency, Gemini quota dependency, and stochastic media QC.
- No accepted production behavior changed.

## 2026-08-14 — Kokoro Local TTS amendment

- Add the owner-authorized `kokoro_local` provider through the common TTS and
  canonical-alignment contracts, with explicit per-project selection, offline
  runtime/model/voice discovery, resumable deterministic WAV chunks, direct
  model token timing, sanitized local failures, and no paid credential gate.

## Unreleased

- Correct Ambient Story planning after Trial A: identify narrative states
  before compatible visual-anchor merging; make preferred asset budgets soft
  with bounded hard maxima; separate visual briefs from narration summaries;
  enforce centralized, priority-aware Flow IMAGE prompt budgets without blind
  truncation; preserve upstream TTS/alignment on visual-policy invalidation; and
  prevent Visual match from passing without selected generated evidence.
- Correct Kokoro Local readiness so Settings and production share one offline,
  load-only runtime/model/voice probe; support explicit durable cache and
  snapshot resolution; and expose actionable missing-model, missing-voice,
  invalid-configuration, and runtime-load states before downstream work.
- Add the post-release `ambient_story` format with durable Quiet Verdict and
  Hidden Mastery profiles, semantic low-count visual chapters, Flow IMAGE-only
  generation policy, deterministic bounded still presentation, style-aware
  subtitles/transitions, narrow resume invalidation, normal Format/Style UI,
  and two provider-free common-compositor demo renders. Existing
  `hybrid_hook` and `full_video_ai` behavior remains separate.

- Record accepted post-v1.0.0 development without creating a new release:
  Goal 10 simplifies the local creator experience to
  `CONTENT → SETUP → CREATE → REVIEW → DONE` across Home, Project, and
  Settings, with Advanced and Diagnostics secondary; product core behavior is
  unchanged.
- Record Goal 11 Flow IMAGE postprocessing: immutable raw provider evidence,
  deterministic locally cleaned and lineage-validated selected derivatives,
  fail-closed unsupported geometry, and QC failure for a remaining visible
  provider mark. Flow VIDEO retains the historical accepted visible-mark
  limitation.
- Redesign the loopback UI around a creator-first Home, recoverable three-step
  New video flow, focused production progress, actionable recovery states,
  dedicated review/completion experiences, and intent-grouped Settings. Keep
  diagnostics and advanced provider detail behind disclosure while preserving
  the canonical CLI, artifacts, services, and production behavior.
- Lock Story Auto V1 production images and videos to Google Flow Web by owner
  decision; close unfinished provider benchmarking while preserving all Flow,
  Gemini API 429, and partial Gemini Web provenance.
- Accept the visible Flow sparkle mark as a documented known limitation, add a
  soft bottom-right composition safe area and right-cleared subtitles, retain
  x1 image enforcement, and keep all naturalness/continuity QC failures active.

- Add structured `NATURAL_SOFT_REALISM` visual DNA, anti-AI-polish prompts,
  production naturalness/watermark QC, and the project-wide x1 image invariant.
- Add deterministic multi-part full-video requests and render coverage,
  repeated-kind production batches, QC-gated thumbnails, and optional bounded
  `NATURAL_SOFT` render finishing.
- Add the loopback-only operator dashboard and shared `OperatorService` for
  project/content, planning, media review, generation, render, provenance, and
  publishing actions while preserving CLI behavior.
- Harden provider and render restarts with capacity preflight, atomic media
  candidates, zero-byte/partial acquisition recovery, planning-stage resume,
  and repository/evidence credential and runtime-import scanning.

- Add the offline Story Auto core foundation: minimal project contract, locking,
  atomic checkpoint store, bounded retry, and CLI content-manifest vertical slice.
- Add provider-neutral TTS request/result contracts, canonical audio manifests,
  canonical alignment validation, and separate TTS/alignment resume identities.
- Add isolated ElevenLabs and Typecast adapters with offline timestamp/chunking
  coverage. Live validation remains credential-gated.
- Add the Gemini planning foundation: an isolated structured-output provider,
  alignment-authoritative story timelines, continuity bibles, durable review
  state, and per-stage checkpoint/resume fingerprints.
- Add deterministic planning/provider tests plus bounded live Gemini 3.5 and
  3.6 fixture validation. The production baseline remains Gemini 3.5 Flash.
- Add provider-independent visual planning: validated `shot_plan.json`,
  deterministic hybrid/full-video `media_plan.json`, compiled continuity and
  shot `generation_requests.json`, dependency ordering, guardrail estimates,
  visual-stage resume fingerprints, and hash-bound shot-plan approval.
- Add an isolated Google Flow provider foundation: dedicated runtime/CDP
  preflight contract, fail-closed composer boundary, append-only generation
  attempt manifest, explicit generation gate, dependency-aware resume, and
  local Pillow/FFprobe validation. Offline evidence passes; live Flow evidence
  remains operator-session-gated.
- Add the production hybrid renderer: exact validated render-plan resolution,
  fail-closed full-video safety, reusable FFmpeg/FFprobe primitives, normalized
  silent IMAGE/VIDEO/HOLD clips, explicit crossfade duration math, SRT/ASS,
  narration/BGM mix, common composition, final validation, and durable final
  manifest provenance.
- Add per-stage/per-shot render checkpoints and real recovery behavior for
  missing final output, missing scene clips, invalid provider selections, and
  unchanged zero-work resume.
- Add Goal 08 production-evidence auditing, current Flow x1 watermark rejection,
  five-point hybrid visual review, unchanged zero-work resume, and verified
  one-clip narrow invalidation. Record clean-provider output and approved
  long-form creative content as explicit release dependencies.
- Add the Goal 08 Gemini media benchmark boundary: live current-model discovery,
  Nano Banana 2/Pro image and reference input, Omni video, resumable Veo jobs,
  atomic validated acquisition, append-only attempt integration, anonymous
  review packaging, contact sheets, and supplemental video frames. Record the
  current zero-quota provider-account block without changing production routing.
- Add Gemini title/description generation and Flow thumbnail requests,
  append-only visual rejection/reconciliation, stable signed-URL attribution,
  and project-bound publishing-package provenance.
- Accept a 71.067-second real 1080p hybrid prototype plus a 5.867-second
  technical representative run using the largest approved local content fixture.
  Record `LONG_FORM_CONTENT_NOT_AVAILABLE`; no creative content was invented.

## 2026-08-12 — Design baseline v1.0.0

- Froze Story Auto V1 product requirements.
- Froze two render modes: `hybrid_hook`, `full_video_ai`.
- Froze TTS providers: ElevenLabs + Typecast.
- Froze Gemini 3.5 Flash as planning baseline and 3.6 Flash as benchmark candidate.
- Froze Google Flow as V1 image/video provider.
- Added explicit review state, generation-request, generation-manifest, render-plan, audio-plan, publishing-package, and final-manifest boundaries.
- Froze CLI-first / UI-after-hybrid strategy.
- Prepared Build OS v1.22 external adoption kit.

No product implementation is accepted in this release baseline.

## 2026-08-12 — Foundation primitives accepted

- Added strict `content.md` narration parsing.
- Added atomic UTF-8 JSON/text artifact publication.
- Added deterministic direct-input SHA-256 fingerprints and focused offline coverage.
- No frozen product/design contracts changed.

## 2026-08-12 — Runtime path isolation accepted

- Added a dedicated Story Auto runtime layout and safe project-relative paths.
- No frozen product/design contracts changed.
