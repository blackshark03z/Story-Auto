# Goal 54 — Cinematic Method Audit

Date: 2026-09-12

## Sources audited

1. `harry0703/MoneyPrinterTurbo`
2. VVSVS Cinematique prompt library
3. `Vincentwei1021/video-shotcraft` (the Tinix page is a discovery/index surface for this repository, not a separate technical source)

## What is useful for Story Auto

### MoneyPrinterTurbo

Useful mainly for orchestration and product ergonomics, not for cinematic generation quality.

Adoptable ideas:
- explicit task/progress state surfaced to UI;
- configurable clip duration and multi-output generation;
- task-local persisted artifacts and atomic JSON replacement;
- graceful degradation for optional downstream media steps;
- separate API / CLI / WebUI surfaces over the same workflow.

Do not copy its stock-material assembly model into Goal 54. Story Auto already has stronger provenance/recovery contracts and needs generated-shot continuity rather than generic material matching.

### VVSVS Cinematique

Useful as a provider-neutral cinematography vocabulary and prompt taxonomy.

Adoptable ideas:
- shot/framing vocabulary: establishing, long, medium, close-up, over-shoulder, POV, overhead, low/high angle;
- camera-motion vocabulary: dolly, pan, tilt, push-in, pull-out, rack focus, steadicam, orbit/360, whip pan;
- prompt dimensions should be separated rather than written as one prose blob: subject/action, framing, camera motion, lens/depth, lighting, composition/mood;
- use the vocabulary as controlled options and test variables, not as literal verbose prompts for every model.

Important limitation: Cinematique is generic prompt guidance; it does not prove that Seedance/Elyum interprets every camera/lens term faithfully. Goal 54 must benchmark a bounded subset at 480p before promotion.

### video-shotcraft

Highest-value source for Goal 54 methodology.

Adoptable ideas:
- maintain a shot-recipe library instead of inventing prompts ad hoc;
- each recipe should carry purpose, energy, suggested duration, parameters, implementation notes, known failure modes, and reference evidence;
- map narrative/function intent to a small set of shot recipes before generation;
- one shot should have one dominant motion idea;
- reserve hold/rest time after key action instead of filling every frame with movement;
- prefer slower readable motion on the first pass; increase motion only with evidence;
- make visual QA continuous, not only a final-stage activity;
- validate exact implementation/reference evidence rather than relying on a recipe name alone;
- deterministic configuration and repeatable fixtures matter for comparing generations;
- build acceptance as evidence-backed rules and counterexamples, not subjective labels alone.

The Remotion-specific implementation, product-UI screenshot capture, BGM beat-sync pipeline, and product-promo SFX library are not directly applicable to Story Auto Full Video V1 and should not be imported wholesale.

## Proposed Goal 54 experiment model

Create a small `Shot Recipe V1` schema for provider research only. Do not add a generalized production abstraction until Elyum runtime evidence justifies it.

Recommended fields:
- `shot_recipe_id`
- `narrative_purpose`
- `framing`
- `camera_motion`
- `subject_motion`
- `motion_intensity`
- `reference_strategy` (`TEXT_ONLY`, `CHARACTER_IMAGE`, `SCENE_IMAGE`, `MULTI_REFERENCE`)
- `duration_seconds`
- `resolution`
- `identity_constraints`
- `environment_constraints`
- `negative_constraints`
- `expected_failure_modes`
- `acceptance_checks`

First research set should stay small:
1. static/locked medium shot;
2. slow push-in medium-to-medium-close-up;
3. slow lateral pan/tracking shot;
4. simple subject turn or short walk;
5. same-character two-shot continuity test;
6. same-character same-location shot-to-shot continuity test.

Run at the lowest supported cost/resolution first (480p, minimum useful duration). Change one variable at a time. Measure identity drift, environment drift, anatomy/motion defects, camera compliance, usable-frame ratio, generation latency, credits consumed, and whether the result can be safely repeated.

## Decision

For Goal 54, adopt the methodology, not the codebases:

`Cinematique vocabulary -> bounded Shot Recipe library -> Elyum low-cost experiments -> evidence-backed recipe promotion -> Story Auto planner integration only after repeatability is proven.`

Do not import a large cinematic prompt library directly into production prompts. Do not introduce a new generic router or Remotion dependency from this audit alone.
