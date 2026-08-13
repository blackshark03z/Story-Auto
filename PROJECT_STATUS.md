# Project Status

## Current accepted state

**DESIGN_FROZEN / HYBRID_PRODUCTION_MVP_ACCEPTED**

Frozen product design: Story Auto V1, 2026-08-12.

The repository contains the frozen product authorities and a production-capable
CLI/application pipeline through hybrid rendering and publishing assets. Goal 08
production-release work is active; local UI and live representative evidence are
not yet accepted.

## Accepted feature inventory

- Primary input: `content.md` with strict `## Narration`.
- Modes: `hybrid_hook`, `full_video_ai`.
- TTS: ElevenLabs + Typecast.
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
- Production media uses `IMAGE output_count=1`, pauses at naturalness QC, and
  rejects visible provider watermarks without deleting rejected attempts.
- `full_video_ai` now partitions long shots into deterministic video request
  parts, supports explicit repeated-kind production batches, and renders only
  complete all-video coverage through the common compositor.
- Optional `NATURAL_SOFT` normalization applies restrained saturation/contrast,
  highlight, and fine-grain finishing without blur or sharpening.
- A loopback-only local operator dashboard now covers project/content status,
  planning, references, shots, prompt edits, replacement/regeneration, production
  QC, safe generation controls, rendering, provenance, and publishing. CLI and UI
  mutations share `OperatorService` and the accepted core services.
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

## Explicitly not accepted yet

- Live operator-session usability acceptance on the representative productions.
- Live multi-shot full-video representative production and visual acceptance.
- A representative approved long-form creative production; no canonical fixture
  was locally available for this baseline.
