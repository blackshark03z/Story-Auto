# Project Status

## Current accepted state

**DESIGN_FROZEN / FOUNDATION_IN_PROGRESS**

Frozen product design: Story Auto V1, 2026-08-12.

The repository contains the frozen product authorities, Build OS adoption tooling,
and accepted offline foundation primitives. Provider, planning, rendering, and UI
implementation have not yet been accepted.

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

## Configuration/schema authority

Normative V1 artifact semantics are in `docs/specs/ARTIFACT_CONTRACTS_V1.md` and `contracts/schemas/`. Secrets are never stored in project artifacts.

## Explicitly not accepted yet

No provider adapter, UI, provider live test, FFmpeg integration, or generated
Story Auto production video has been accepted at this baseline. The remaining
Foundation work includes project configuration/model, lock/checkpoint/retry
behavior, and the CLI skeleton.
