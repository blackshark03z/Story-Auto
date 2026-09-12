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

The live Elyum account has 150 starter Credits and one kill shown for the current
period. The exact estimate is authoritative at run time.

Current published discovery rates imply roughly:

- Seedance 2.0 Mini, 480p: ~5 Credits/s, minimum 4 s -> ~20 Credits/attempt.
- Seedance 2.5, 480p: ~9 Credits/s, minimum 4 s -> ~36 Credits/attempt.

Use the cheaper Seedance family member to screen camera grammar, then confirm
only the winning patterns on Seedance 2.5.

### Mandatory set — maximum nominal held/kept budget 132 Credits

| ID | Model | 4 s recipe | Reference | Purpose | Nominal estimate* |
| --- | --- | --- | --- | --- | ---: |
| R1 | Seedance 2.0 Mini | `MEDIUM_EYE_LEVEL + LOCKED + SLOW_HEAD_TURN` | TEXT_ONLY | baseline / prompt clarity | ~20 |
| R2 | Seedance 2.0 Mini | `MEDIUM_EYE_LEVEL + SLOW_PUSH_IN + HOLD_WITH_MICROMOTION` | TEXT_ONLY | camera compliance | ~20 |
| R3 | Seedance 2.0 Mini | `MEDIUM_EYE_LEVEL + SLOW_LATERAL_TRACK + HOLD_WITH_MICROMOTION` | TEXT_ONLY | lateral motion compliance | ~20 |
| R4 | Seedance 2.5 | best R1–R3 camera recipe + `SLOW_HEAD_TURN` | CHARACTER_IMAGE | identity lock | ~36 |
| R5 | Seedance 2.5 | second shot, same character/location, one changed action | CHARACTER_PLUS_SCENE_IMAGE | shot-to-shot continuity | ~36 |

`*` Re-estimate immediately before every run. Do not submit if the live estimate
would make the bounded research budget exceed the available balance.

The nominal total is ~132 Credits if every result is kept/held. This deliberately
leaves an ~18-credit safety margin. Do not spend the reserve merely to complete a
matrix.

### Optional R6

Run one additional 4-second test only if a prior hold was released, live pricing
is lower than the nominal budget, or new Credits are explicitly available. R6
should isolate **subject movement** using a locked camera:

`MEDIUM_EYE_LEVEL + LOCKED + SHORT_WALK_2_STEPS`.

## One-variable rule

Between adjacent tests, change one primary variable whenever possible. In
particular:

- R1 -> R2 changes camera behavior;
- R2 -> R3 changes camera behavior;
- R3 -> R4 changes model + reference strategy only after a camera recipe wins;
- R4 -> R5 preserves model/character and changes shot action/context minimally.

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

Do not assume the Elyum Free account has developer/API access solely because it
has 150 Credits. Current public pages are not perfectly consistent: model/MCP
pages describe shared Studio/MCP/REST access, while the pricing table explicitly
lists `API + MCP access` under Plus. The real account is the authority.

Before implementing the Elyum Story Auto adapter:

1. open the logged-in account's Developer/API area;
2. verify whether the Free account can create an API key or authorize MCP;
3. if yes, run read-only `account`, `models` and `estimate` checks first;
4. record scopes/daily cap without storing the key in Git;
5. only then implement generation around `clientRef` + durable `jobId`.

If Free API/MCP is unavailable, do **not** pay or upgrade automatically and do not
build browser automation. Use the web Studio only for bounded cinematic-method
research and keep BytePlus as the production API baseline until the Owner chooses
otherwise.

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
