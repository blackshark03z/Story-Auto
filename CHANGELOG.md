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
