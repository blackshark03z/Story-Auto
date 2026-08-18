# Roadmap

Stable release baseline: **Story Auto v1.0.0 Stable** at
`6dc3188a16bd1ae4f84906f891083ec6c0651154` (`v1.0.0`). The accepted
post-release development state includes Goal 10 UX/UI simplification, Goal 11
Flow image mark postprocessing, Goal 12 state synchronization, and local
Goals 13–17 corrective candidates; none is a new release version. Goal 17 is
the current implementation anchor for Flow queue/reconciliation behavior.

The next production action is not a normal new batch: resume preserved Trial A
(`ambient_story + quiet_verdict`) only through the Goal 17 reconciliation and
serial queue-barrier path. Reconcile its earliest unresolved attempt before any
Flow activation; unresolved/ambiguous attribution halts the queue. Trial B
(`ambient_story + hidden_mastery`) remains unstarted and blocked behind that
safe Trial A resolution.

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

## Phase 10 — Ambient Story foundation — LOCAL CANDIDATE

- [x] Durable `ambient_story` format and two initial style profiles.
- [x] Semantic visual chapters with low image budgets and no AI video.
- [x] Deterministic bounded image presentation through the common compositor.
- [x] Offline Quiet Verdict and Hidden Mastery engineering demos.
- [~] Trial A: preserved Quiet Verdict project with completed narration and
  alignment; resume only through Goal 17 reconciliation/barrier, never by
  direct resubmission or newest-output selection.
- [ ] Trial B: real Hidden Mastery production, not started; blocked until Trial
  A's earliest unresolved Flow attempt is safely reconciled and the barrier is
  released.

## Deferred

- additional visual providers;
- smart provider routing;
- SFX/ambience automation;
- YouTube upload;
- cloud queue/multi-user/database;
- generic timeline editor.
