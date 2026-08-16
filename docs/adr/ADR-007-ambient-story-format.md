# ADR-007: Ambient Story production format

- Status: Accepted with Goal 15 visual-planning correction; Trial A resume pending
- Date: 2026-08-15

## Context

Long-form fictional narration can carry retention without dense scene-per-line
visual generation. The existing `hybrid_hook` and `full_video_ai` policies are
valuable but can spend visual-generation and QC effort where a smaller number
of excellent narrative-state images would be more appropriate.

## Decision

Add `ambient_story` to the existing render-mode abstraction. Do not create a
parallel production-format hierarchy or a second pipeline.

Ambient Story reuses narration, TTS, canonical alignment, `story_timeline`,
continuity, `shot_plan`, `media_plan`, `generation_requests`, the Flow IMAGE
adapter and Goal 11 clean derivative, the generation manifest, `render_plan`,
the image compiler, common compositor, subtitles, BGM, resume, QC, and
publishing package.

Its planning unit is a **visual chapter** expressed as a long-lived shot over
contiguous timeline scenes. Planning is explicitly two-stage: identify
meaningful narrative-state candidates, then merge adjacent candidates only when
one truthful visual anchor can support them. Boundaries are semantic—not fixed
elapsed-time intervals—and semantic compatibility takes precedence over asset
count.

The target is high narrative value per generated asset. These ranges are
preferences, not semantic hard caps:

- `quiet_verdict`: preferred 2–5, hard maximum 8 chapter images;
- `hidden_mastery`: preferred 4–7, hard maximum 10 chapter images.

Exceeding a preferred maximum is permitted only for incompatible narrative
states and records `SEMANTIC_STATE_INCOMPATIBILITY`. Exceeding a hard maximum
fails planning instead of silently merging misleading states.

Both profiles retain `NATURAL_SOFT_REALISM` as base visual DNA. Profiles are
small data/policy records, not renderer forks or arbitrary tuning bags.

Every Ambient visual chapter is `IMAGE / REQUIRED`. Flow video requests are
forbidden and temporal video QC is `NOT_APPLICABLE`. Semantic relevance,
naturalness, visible-provider-mark, continuity, and render QC remain active.

The image compiler supports only `STATIC`, `SUBTLE_PUSH`, `SUBTLE_PULL`,
`SUBTLE_PAN_LEFT`, `SUBTLE_PAN_RIGHT`, and `MICRO_DRIFT`. Total scale change is
bounded to 1–3%; translation is likewise bounded. A seeded, low-strength fine-
grain primitive supplies optional continuous micro-activity. Presentation
parameters are deterministic render inputs and do not alter provider identity.

An Ambient chapter stores its broad narration summary separately from a concise
visual brief: narrative function, visual anchor, dominant subject, environment,
state, motif, continuity requirements, and bounded optional context. The Flow
compiler consumes only that visual brief. Long `SUPPORTIVE` anchors are valid
when justified; `ATMOSPHERIC` remains explicit and cannot bypass semantic QC.

The canonical Flow IMAGE prompt hard limit is 1,200 characters. Ambient
compilation targets at most 1,100 characters, removes complete lower-priority
optional fields first, and never slices the final prompt. Identity,
environment, continuity, safe-area, style, and negative constraints are
required. If they cannot fit, planning fails before provider submission with
`AMBIENT_VISUAL_BRIEF_OVER_BUDGET` and records the excessive field.

Style prompt semantics do alter generation identity, but local-only motion or
overlay enablement invalidates render descendants only. Narration, TTS,
alignment, timeline, and continuity do not invalidate solely because the
Ambient visual style or presentation changes.

## Consequences

- Existing `hybrid_hook` and `full_video_ai` media, hook, motion, temporal-QC,
  and render behavior remain separate and unchanged.
- Fewer generated images make continuity and semantic errors more visible, so
  the existing continuity bible and exact selected-asset mapping remain strict.
- Normal UI exposes Format and, only for Ambient Story, Quiet Verdict or Hidden
  Mastery Style. Motion/effect/budget internals remain diagnostics-only.
- Review reports visual match as Not checked/Pending until selected generated
  evidence exists. A planning/compiler failure invalidates visual approval and
  surfaces an actionable regeneration state; its failure code remains under
  technical details.
- Offline demos validate engineering behavior without provider calls. They are
  not publishable stories or evidence of long-form audience performance.

## Deferred

`viper_protocol`, `legacy_heart`, AI video for Ambient Story, a keyframe editor,
3D parallax, complex particles, new providers, story/title/thumbnail engines,
channel-specific forks, and analytics integration remain out of scope.

## Production-trial gate

Trial A completed its 467.975-second Kokoro narration and alignment, then paused
before any Flow call when the original visual plan exceeded the prompt limit.
Goal 15 corrects that planning path without invalidating narration, audio, or
alignment. Resume the preserved Trial A project from visual planning after this
corrective passes; do not create a replacement project. Trial B remains pending.
