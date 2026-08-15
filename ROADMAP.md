# Roadmap

Stable release baseline: **Story Auto v1.0.0 Stable** at
`6dc3188a16bd1ae4f84906f891083ec6c0651154` (`v1.0.0`). The accepted
post-release development state includes Goal 10 UX/UI simplification and Goal
11 Flow image mark postprocessing; neither is a new release version.

There is no active engineering feature goal. Next mode is normal product use:
run a real production trial through the normal Story Auto UI, observe any real
defect, then open a narrow corrective goal with regression coverage.

## Phase 0 — Design + Build OS baseline — ACCEPTED

- Freeze product requirements and architecture.
- Freeze artifact/failure/acceptance contracts.
- Adopt external Build OS v1.22 Project Lifecycle Kit + Continuity.

## Phase 1 — Foundation

- [x] Runtime project paths and Story Auto-only runtime-root isolation.
- [x] strict `content.md` parser.
- [x] atomic I/O and deterministic fingerprints.
- Project lock, checkpoints, bounded retry.
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

- [x] 60–90 second live hybrid prototype.
- [x] technical representative hybrid production; approved long-form fixture was unavailable.
- [x] metadata + Flow thumbnail.

## Phase 8 — Local UI — ACCEPTED

Goal 10 acceptance is complete. The creator workflow is
`CONTENT → SETUP → CREATE → REVIEW → DONE`, with Home, Project, and Settings
as the primary surfaces; Advanced and Diagnostics remain secondary.

Only after Phase 7 pipeline is stable.

- project/settings;
- plan/reference review;
- shot status + per-shot regenerate/override;
- generation progress;
- render/final/publishing package.

UI must use existing application services.

## Phase 9 — Full-video V1 — IMPLEMENTED

The V1 implementation, continuity/resume hardening, and explicit cost
confirmation are complete. Do not schedule speculative follow-on work here;
use defect-driven corrective goals after normal production trials.

## Deferred

- additional visual providers;
- smart provider routing;
- SFX/ambience automation;
- YouTube upload;
- cloud queue/multi-user/database;
- generic timeline editor.
