# ADR-007: Ambient Story production format

- Status: Accepted for offline foundation; real production trials pending
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
contiguous timeline scenes. Boundaries are chosen from semantic narrative state
changes—not fixed elapsed-time intervals. The target is high narrative value
per generated asset:

- `quiet_verdict`: 2–5 chapter images, cool-neutral restrained institutional tension;
- `hidden_mastery`: 4–7 chapter images, warm tactile realism and recurring-object continuity.

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
- Offline demos validate engineering behavior without provider calls. They are
  not publishable stories or evidence of long-form audience performance.

## Deferred

`viper_protocol`, `legacy_heart`, AI video for Ambient Story, a keyframe editor,
3D parallax, complex particles, new providers, story/title/thumbnail engines,
channel-specific forks, and analytics integration remain out of scope.

## Production-trial gate

After the offline foundation passes, run one real Quiet Verdict trial and one
real Hidden Mastery trial. Their cost, continuity, visual quality, operational
friction, and audience suitability determine later tuning or style expansion.
