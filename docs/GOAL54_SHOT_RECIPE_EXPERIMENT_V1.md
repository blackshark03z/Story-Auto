# Goal 54 — Shot Recipe Experiment V1

Date: 2026-09-12

## Purpose

Find a small, repeatable cinematic generation method before Story Auto spends
provider credits at production scale. The experiment optimizes for repeatability,
identity continuity, camera compliance and safe cost — not for one unusually
beautiful lucky generation.

This is a research contract, not a new production abstraction. Do not wire these
recipes into the planner until runtime evidence shows that the recipe concepts are
repeatable on the selected provider/model.

## Evidence authority

- The real Elyum Free account is confirmed by the Owner to show 150 Credits.
- Current provider price/model capability must be re-read from the live account
  or `elyum_estimate` before each generation; web/docs pricing is discovery
  evidence only and may change.
- Large preview/output artifacts stay outside canonical source. Record only
  hashes, provider/job identity, settings, scores and evidence pointers in Git.

## Controlled vocabulary V1

Use only a bounded vocabulary during the first pass. Avoid generic phrases such
as "cinematic camera" when one observable camera behavior can be named.

### Framing

- `MEDIUM_EYE_LEVEL`
- `MEDIUM_CLOSE_UP_EYE_LEVEL`
- `WIDE_EYE_LEVEL`

### Camera motion

- `LOCKED`
- `SLOW_PUSH_IN`
- `SLOW_LATERAL_TRACK`

### Subject motion

- `HOLD_WITH_MICROMOTION`
- `SLOW_HEAD_TURN`
- `SHORT_WALK_2_STEPS`

### Reference strategy

- `TEXT_ONLY`
- `CHARACTER_IMAGE`
- `CHARACTER_PLUS_SCENE_IMAGE`

Do not test orbit, whip-pan, handheld shake, multi-action choreography or long
continuous movement in the first pass. They combine too many failure variables.

## Provider-neutral prompt structure

Compile each experiment from the same ordered fields:

1. **Subject identity** — stable physical description or explicit reference.
2. **Environment** — one stable location with only necessary visual facts.
3. **Action** — one dominant subject action.
4. **Framing** — one controlled framing term.
5. **Camera** — one dominant camera motion.
6. **Continuity constraints** — face, hair, wardrobe, location layout and key
   objects that must not drift.
7. **Negative constraints** — only known failure modes relevant to that recipe.

Example structure, not a provider-specific final prompt:

```text
Subject: same adult woman, shoulder-length dark hair, beige jacket.
Environment: quiet daylight apartment living room, large window on camera-left.
Action: slowly turns her head toward the window, then holds.
Framing: medium eye-level shot.
Camera: locked tripod; no pan, tilt, zoom or orbit.
Continuity: preserve face, hairstyle, jacket, window position and room layout.
Avoid: identity change, wardrobe change, extra limbs, sudden camera movement.
```

The compiler should prefer concrete observable motion over lens/film-brand
ornament. Lens, film stock and resolution adjectives are not promoted until they
show measurable value on Seedance.

## Golden fixture

Keep the semantic fixture constant for all first-pass tests:

- one adult character;
- one simple indoor location;
- one neutral wardrobe;
- one simple action at a time;
- 16:9;
- lowest useful resolution;
- no dialogue requirement;
- no scene cuts inside one generation.

For reference-driven tests use one fixed character image and, when needed, one
fixed location image. Do not regenerate the reference between recipes.

## Credit-aware experiment order

At the start of R1, the live Elyum Free account had 150 Credits and one kill
available. R1 was later Kept for 20 Credits; the current verified balance for the
new xianxia branch is 130 Credits with kills left 1/1. The 2026-09-12 live MCP
`elyum_estimate` results below remain historical model-cost evidence:

| Model / mode | 4 s / 480p live estimate |
| --- | ---: |
| Seedance 2 Fast T2V | 44 Credits |
| Seedance 2 Mini T2V | 64 Credits |
| Seedance 2.5 T2V | 76 Credits |
| Seedance 2 Fast I2V | 44 Credits |
| Seedance 2.5 Reference | 76 Credits |
| Seedance 2.5 I2V | UNVERIFIED — one read-only estimate timed out |

The previous five-attempt ~132-Credit plan is invalid and is superseded. The
research goal is identity/continuity plus camera compliance, so prioritize
reference-driven video instead of spending scarce Credits on text-only breadth.

### Historical bounded set — superseded 2026-09-13

R1 completed and was Kept. The planned R2 Seedance 2.5 Reference step below is
preserved as historical intent but is **paused and not executed**. Current
research authority moved to `docs/GOAL54_XIANXIA_3D_RESEARCH_PLAN_V1.md`; the
post-Keep Elyum balance is 130 Credits with kills left 1/1. This file remains the
general shot-recipe methodology and historical R1 record.

#### Original bounded set — maximum estimated spend 120 Credits

| ID | Model | 4 s recipe | Reference | Purpose | Live estimate |
| --- | --- | --- | --- | --- | ---: |
| R1 | Seedance 2 Fast I2V | `MEDIUM_EYE_LEVEL + SLOW_PUSH_IN + HOLD_WITH_MICROMOTION` | CHARACTER_IMAGE | cheap camera + identity screening | 44 |
| R2 | Seedance 2.5 Reference | same framing/camera, same character; add stable scene reference if supported | CHARACTER_IMAGE or CHARACTER_PLUS_SCENE_IMAGE | higher-quality identity/reference confirmation | 76 |

Total estimated maximum: **120 / 150 Credits**, preserving 30 Credits. Re-run
`elyum_estimate` immediately before each dispatch; estimate drift that would make
the bounded spend exceed available balance blocks submission.

Do not spend the remaining 30 Credits merely to fill a matrix. A third generation
requires either released held Credits, newly available Credits, or an explicit new
bounded research decision supported by evidence from R1/R2.

## One-variable rule

R1 and R2 preserve the same subject, character reference, semantic action,
framing, camera motion, duration, resolution and aspect ratio. R2 changes only
the model/reference capability needed to test whether Seedance 2.5 Reference
materially improves identity/reference adherence over the cheaper Fast I2V path.
If R2 supports an additional scene reference, record that as a deliberate second
variable and do not attribute all improvement to the model alone.

Do not change prompt style, duration, resolution, subject, environment and camera
at the same time; such a result cannot teach Story Auto what caused improvement.

## Manual acceptance rubric V1

Score each result after the preview is ready. Do not use "looks good" as the
only oracle.

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Camera compliance | wrong/chaotic | partly follows | clearly follows requested motion |
| Subject action | wrong/missing | approximate | correct and readable |
| Identity stability | material drift | minor drift | stable face/body/wardrobe |
| Environment stability | layout/object drift | minor drift | stable scene |
| Anatomy / physical motion | unusable artifact | visible but tolerable issue | clean/readable motion |

Also record:

- usable-frame ratio estimate (`0–100%`);
- latency to preview;
- Credits estimated/held/charged;
- model + exact settings;
- provider job identity when available;
- whether the prompt required an undocumented workaround.

### Critical-failure flags

Any one of these prevents recipe promotion regardless of numeric score:

- major identity replacement;
- extra/missing limb or severe body deformation;
- camera direction opposite to the requested move;
- unexpected cut/scene replacement;
- environment replacement that breaks continuity;
- provider/job ownership cannot be tied to the request.

## Promotion rule

A single success makes a recipe only `RESEARCH_CANDIDATE`.

Promote a recipe toward Story Auto planning only when:

1. it scores at least 8/10 with no critical failure;
2. its camera/action behavior is clearly attributable to the requested recipe;
3. the same recipe is repeated successfully on another fixture or another take;
4. its provider job/result can be recovered safely;
5. the prompt does not depend on fragile browser-only behavior.

If free Credits are insufficient for repeatability proof, stop at
`RESEARCH_CANDIDATE` and preserve the evidence rather than weakening this rule.

## API / MCP boundary

The real Elyum Free account has now crossed the read-only runtime gate:

1. the Owner created an API key outside the repository;
2. MCP Streamable HTTP initialized successfully;
3. `elyum_account`, `elyum_models`, and `elyum_estimate` are available and callable;
4. account result initially confirmed `Free`, balance 150, kill limit 1 / kills left 1; post-R1 Keep verification reports balance 130 with kills still 1 / 1;
5. model catalog exposes Seedance Fast/Mini/2.5 T2V, Fast/2.5 I2V, and 2.5 Reference paths;
6. live read-only estimates are recorded above.

R1 has now been dispatched, recovered by durable `jobId`, visually reviewed and
Kept. The research-only Elyum adapter implements the narrow idempotent
`clientRef` + durable `jobId` contract with explicit Keep/Kill boundaries.
Current generation order is governed by
`docs/GOAL54_XIANXIA_3D_RESEARCH_PLAN_V1.md`. Browser automation remains
forbidden for the Full Video production path.

## Research output

For every attempt append a compact record to Goal 54 evidence containing:

- recipe ID;
- provider/model/settings;
- prompt fingerprint;
- reference fingerprint(s), if any;
- live estimate and final Credit consequence;
- job/result identity if available;
- five rubric scores + critical flags;
- evidence artifact pointer/hash;
- verdict: `REJECTED`, `RESEARCH_CANDIDATE`, or `REPEATABILITY_PROVEN`.

This experiment ends when enough evidence exists to choose a small recipe set or
when the bounded free-credit budget is exhausted. It must not silently expand
into broad model benchmarking.
