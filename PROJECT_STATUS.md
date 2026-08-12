# Project Status

## Current accepted state

**DESIGN_FROZEN / FOUNDATION_IN_PROGRESS**

Frozen product design: Story Auto V1, 2026-08-12.

The repository contains the frozen product authorities, Build OS adoption tooling,
the accepted audio foundation, and the Gemini story-planning foundation. Rendering,
visual generation, and UI implementation remain deferred.

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
- Bounded live Gemini fixture validation passed for `gemini-3.5-flash`; the
  identical `gemini-3.6-flash` benchmark was available and passed without
  changing the production baseline. Safe metrics are in runtime evidence.

## Configuration/schema authority

Normative V1 artifact semantics are in `docs/specs/ARTIFACT_CONTRACTS_V1.md` and `contracts/schemas/`. Secrets are never stored in project artifacts.

## Explicitly not accepted yet

No visual provider adapter, UI, FFmpeg integration, or generated Story Auto
production video has been accepted at this baseline.
