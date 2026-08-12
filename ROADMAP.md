# Roadmap

## Phase 0 — Design + Build OS baseline — ACCEPTED

- Freeze product requirements and architecture.
- Freeze artifact/failure/acceptance contracts.
- Adopt external Build OS v1.22 Project Lifecycle Kit + Continuity.

## Phase 1 — Foundation

- Project model/paths.
- strict `content.md` parser.
- atomic I/O, project lock, fingerprints/checkpoints, bounded retry.
- CLI skeleton + tests.

## Phase 2 — Audio foundation

- Port/adapt ElevenLabs.
- Port/adapt Typecast.
- Canonical alignment.
- Preserve provider-specific proven settings without silent cross-provider fallback.

## Phase 3 — Planning contracts

- Gemini 3.5 Flash provider.
- Story timeline.
- Continuity bible.
- Shot plan.
- Media plan.
- Review/approval state.
- Prompt/request compiler.

## Phase 4 — Local media vertical slice

No live provider calls.

- local PNG + synthetic/local MP4;
- image/video/hold normalization;
- subtitles;
- optional local BGM;
- exact render plan;
- final MP4.

## Phase 5 — Flow image

- Isolated Story Auto profile/session.
- Port/adapt proven image browser mechanics.
- Manifest-aware idempotency.
- reference generation + approval.

## Phase 6 — Flow video

- Capability discovery.
- video generation workflow.
- download + FFprobe validation.
- ambiguous-timeout reconciliation.

## Phase 7 — Hybrid production MVP

- 60–90 second live hybrid prototype.
- full-length hybrid pipeline capability after operator cost confirmation.
- metadata + Flow thumbnail.

## Phase 8 — Local UI

Only after Phase 7 pipeline is stable.

- project/settings;
- plan/reference review;
- shot status + per-shot regenerate/override;
- generation progress;
- render/final/publishing package.

UI must use existing application services.

## Phase 9 — Full-video V1

- 2–3 minute all-video prototype.
- continuity/resume hardening.
- explicit cost confirmation.
- then one representative 18–24 minute run.

## Deferred

- additional visual providers;
- smart provider routing;
- SFX/ambience automation;
- YouTube upload;
- cloud queue/multi-user/database;
- generic timeline editor.
