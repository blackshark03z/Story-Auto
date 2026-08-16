# Goal 15 validation evidence

## Outcome

`STORY-AUTO-GOAL-15-AMBIENT-VISUAL-PLANNING-AND-PROMPT-BOUNDS` corrects Ambient Story visual planning, prompt construction, and evidence-aware review state without resuming the Trial A production run.

## Trial A preservation

- Project: `prj_4f895eb1436c42c4ba5b908381b14fd1`
- Content SHA-256: `92bb76c744706367d560c37eec1e3303430034c0444496d76a33a87489b3e3f9`
- Narration SHA-256: `840385b68fc52b6a8c48e4a392be862daa03ae5653efb99da19fce49d3f413a8`
- Alignment SHA-256: `af4618baf991ba47e9bfdc7e356e6374cf96c4ed634d9ef22747bd963c78f814`
- Narration duration: `467.975` seconds
- Alignment segments: `123`
- The live project was read for regression input only. No Flow, Gemini, or paid TTS call was made, and Trial B was not started.

The Trial A regression fixture produces eight semantically bounded image chapters:

1. `0.0–19.65`
2. `19.65–95.15`
3. `95.15–130.0125`
4. `130.0125–227.9`
5. `227.9–278.9875`
6. `278.9875–322.7`
7. `322.7–414.1`
8. `414.1–467.975`

The compiled Trial A plan contains eight shot requests and six continuity references, all `IMAGE`, with zero video requests. The longest compiled prompt is `1072` characters. The only budget exception is `SEMANTIC_STATE_INCOMPATIBILITY`.

## Planning and prompt policy

- Quiet Verdict preferred range: `2–5`; hard maximum: `8`.
- Hidden Mastery preferred range: `4–7`; hard maximum: `10`.
- Flow hard prompt limit: `1200` characters.
- Ambient internal prompt target: `1100` characters.
- Compaction removes whole optional supporting-context and motif fields in priority order. It never raw-slices required subject identity, environment, continuity, safe-area, style, or negative constraints.
- An irreducible brief fails with `AMBIENT_VISUAL_BRIEF_OVER_BUDGET` before provider dispatch.
- A chapter count above the style hard maximum fails with `AMBIENT_CHAPTER_HARD_MAX_EXCEEDED`.
- Planning failures invalidate plan approval, retain upstream content/audio/alignment/timeline/continuity evidence, remove only stale visual descendants, and expose a regeneration-required user state.

## Automated verification

- Focused Goal 15, Ambient Story, and UI coverage: `33` tests, PASS.
- Full unit suite: `163` tests, PASS.
- `python tools/quality_gate.py`: PASS.
- `python tools/security_gate.py`: PASS; `YOUTUBE_AUTO_RUNTIME_IMPORTS=0`.
- `node --check story_auto/ui/static/app.js`: PASS.
- `git diff --check`: PASS, with platform line-ending notices only.
- Failure-path provider counter: `0`; narration and alignment hashes preserved.
- Stale-policy rebuild: content, narration, alignment, timeline, and continuity hashes preserved; visual descendants regenerated.
- Rendered UI review: PASS at desktop and 700 px; browser warning/error log count `0`.

## Frozen-release regression metadata

- Tag `v1.0.0` remains at `484b5cef4715b95db8bc2c06b6197cfae92c5ff8`.
- Video001 master SHA-256 remains `9b5d794fdf16575616a57a0eb91a437da232a9c59313eaa88b7a39daa6c71e81`.
- Video002 master SHA-256 remains `69c4d2abf7232e4e5ff9cfb9e6b2e6302539cd56ecc8cecc50072f8c10bf495b`.
- `VERSION`, `docs/releases/**`, and `DESIGN_FREEZE.md` are unchanged.

## Deferred scope

The previously documented project-title derivation issue remains deferred. Trial A must resume in the existing project only after this goal is accepted; no Trial B run is part of Goal 15.
