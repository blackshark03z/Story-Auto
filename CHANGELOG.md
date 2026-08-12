# Changelog

## Unreleased

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
