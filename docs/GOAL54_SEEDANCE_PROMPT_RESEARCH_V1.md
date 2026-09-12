# Goal 54 — Seedance Prompt Research V1

Date: 2026-09-13
Status: **ACCEPTED RESEARCH DIRECTION — X1C NOT YET DISPATCHED**
Scope: Elyum / Seedance 2 Fast I2V, 4 s, 480p, `XIANXIA_3D_V1`

## Research question

Find the smallest repeatable prompt structure that preserves the canonical xianxia
anchor while improving material softness (skin/fabric/wood) and retaining one
clear camera behavior. The target is not a richer prose prompt; it is higher
instruction clarity per token with lower semantic conflict.

## Evidence considered

1. BytePlus ModelArk — Dreamina Seedance 2.0 series prompt guide. The official
guide recommends engineering-style instructions, concise descriptions, avoiding
redundancy/semantic conflicts, using reference assets to carry spatial detail,
and structuring text around subject/action/environment/light/camera/style/quality/
constraints. It also recommends slow/gentle coherent motion and explicit style
constraints for 3D Chinese-style animation/xianxia.
2. Current Story Auto X1/X1B runtime evidence. X1 preserved the scene/camera but
Owner review rejected the surface as too glossy. X1B changed only the material/
lighting language toward soft-matte and reduced measured highlight fraction from
~9.70% to ~8.45%, but human visual acceptance remains unresolved.
3. Owner-provided long-form xianxia master prompt. Useful vocabulary includes
natural matte skin, gentle subsurface softness, realistic shadow transitions,
restrained specular response, silk weave/fabric thickness, controlled metallic
reflections, natural gemstone response, soft cinematic depth, and the explicit
rejection of wet/oily/plastic/waxy/metallic/porcelain skin.

## Key finding — split prompt responsibilities

The long-form master prompt is valuable as a **Visual Constitution / Anchor
Generation Spec**, not as the per-shot Seedance I2V prompt. Its identity, anatomy,
pose, costume, environment, skin/material, lighting and negative sections are too
broad to send verbatim to a 4 s I2V shot whose reference image already defines
most spatial appearance.

Use three layers instead:

1. **Visual Constitution** — long form; used when creating/revising canonical
   anchor/reference assets. Owns face/costume/anatomy/material/art-direction rules.
2. **Shot Prompt** — short form; sent to Seedance. Owns reference lock, one motion,
   one camera move, one style/material delta, and a few critical constraints.
3. **Acceptance Rubric** — never sent to the model. Owns visual QA and pass/fail.

This prevents the model from being asked to simultaneously reconstruct anatomy,
redesign costume, preserve identity, alter material response and animate motion.

## What to retain from the Owner master prompt

For Seedance I2V, retain only the vocabulary that directly addresses the observed
failure:

- natural matte skin;
- soft diffuse illumination / gentle shadow transitions;
- broad soft highlight roll-off;
- restrained skin specular response;
- matte-to-soft-satin silk rather than glossy fabric;
- soft diffuse wood response;
- antique gold / jade reflections remain localized and controlled;
- no wet, oily, waxy, plastic, metallic or porcelain-like skin.

Do **not** import into the current X1 shot prompt:

- full body-proportion rules;
- leg-anatomy rules;
- seated/half-reclining pose design;
- bust/neckline redesign;
- high side openings / costume redesign;
- 50–85 mm wording when the frame is already fixed by the anchor;
- long anatomy defect catalogs;
- unrelated background alternatives;
- `crisp 4K`, heavy HDR, `polished CG`, high-gloss jewelry language;
- pore/peach-fuzz realism if it causes live-action drift away from donghua.

Those remain useful only when creating a new anchor or when the specific failure
requires them.

## Prompt compiler V2 — reference-first, motion-first

For one-shot I2V, compile in this order:

1. `REFERENCE LOCK` — one sentence: use the canonical image as exact visual anchor;
   preserve identity/costume/scene/color palette.
2. `STYLE/MATERIAL TARGET` — one sentence describing the desired surface response,
   not a long rendering manifesto.
3. `SUBJECT MOTION` — one small action/micro-motion.
4. `CAMERA` — one camera move only.
5. `CONTINUITY` — lighting/composition remain stable.
6. `CRITICAL CONSTRAINTS` — 3–6 failure constraints maximum, chosen from actual
   observed failures rather than a generic negative dictionary.

Parameters (duration, resolution, aspect ratio, audio) stay in API fields rather
than prose.

## Recommended language changes

Prefer positive, observable targets:

- `soft matte skin with broad, low-intensity highlights`
- `soft-satin silk; folds remain readable without hard glossy streaks`
- `wood remains softly diffuse`
- `gold and jade carry small localized reflections only`
- `lighting remains diffuse with gentle tonal transitions`

Avoid ambiguous marketing words that previously correlated with unwanted gloss:

- `polished CG`
- `high dynamic range`
- `crisp 4K-quality finish`
- `premium game-character render`
- repeated `realistic / high-end / cinematic / detailed` adjective stacks.

## Candidate X1C — concise matte-soft prompt

Purpose: compare prompt architecture, not model/settings/anchor. Same canonical
anchor, Seedance 2 Fast I2V, 4 s, 480p, 16:9, audio off, one slow push-in.

```text
Use the canonical reference image as the exact visual anchor. Preserve the same
adult Chinese cultivator, face, half-up black hair and silver-blue hairpin, white
and pale-blue hanfu, teal sash, jade pendant, mountain pavilion, misty peaks,
waterfall, and blue-white-gold dawn palette.

Keep the existing 3D Chinese xianxia/donghua style, but render the surfaces softer
and less glossy: natural matte skin with broad low-intensity highlights, soft-satin
silk with readable folds and no hard glossy streaks, softly diffuse wood, and only
small controlled reflections on gold and jade. Lighting stays soft and diffuse
with gentle tonal transitions.

One slow smooth push-in only. She remains almost still: natural breathing, one
subtle blink, and a gentle breeze moving a few hair strands and sleeve edges.
Keep the existing composition and lighting stable throughout. One character only;
no scene change, no style shift, no wet/waxy/plastic skin, no harsh specular
patches, no camera pan/tilt/orbit.
```

The candidate deliberately removes most identity re-description and generic
negative anatomy terms because the canonical image already supplies those facts.

## Why X1C is preferred over simply extending X1B

X1B is directionally better but still contains ~1.7k characters and repeats
identity/environment/negative detail. X1C tests the official Seedance principle:
let the image carry the spatial state, while text directs the temporal change and
one material-style correction. If X1C is visually softer without identity or
scene loss, Prompt Compiler V2 becomes the research default.

## Multi-reference guidance for later work

Seedance supports multi-image/multi-perspective references, but references must
have explicit jobs. For future character work:

- prefer separate clean single-subject images rather than a crowded multi-view
  collage when duplicate/twin artifacts are a risk;
- assign each reference a role (face/identity, costume, environment, or style);
- do not ask two references to control the same attribute unless intentional;
- keep the per-shot text focused on the change, not on reconstructing every
  reference detail.

The current Fast-I2V Elyum experiment remains one canonical anchor only; this
research does not authorize a new multi-reference adapter or production routing.

## Experiment rule

Do not dispatch X1C until the Owner chooses to continue after reviewing X1B. If
X1C is authorized, keep anchor/model/settings/camera/micro-motion fixed and change
only the prompt architecture/material language. Compare X1, X1B and X1C against
exact provenance-bound review surfaces.

Promotion rule:

- `PROMPT_V2_CANDIDATE`: one X1C visually passes surface softness + continuity;
- `PROMPT_V2_REPEATABLE`: a second distinct shot preserves the same style target;
- only then may Story Auto planner use the compiler as a default.

No prompt result alone changes production routing.

## Frozen X1C candidate after Anchor V2 selection

The next authorized comparison candidate is X1C. Byte-level binding of the Owner-selected `XIANXIA_ANCHOR_V2` is complete at `D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_anchor_v2.png`, SHA-256 `569030979570518ca7ed7fedd9499065f499b11977eb5131ce436dad5e5ca42c`. Exact local prompt path:

`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1c_prompt.txt`

SHA-256:

`ed71f3e6edbee061427b9efc1fa265dd4bddd6637adaf3d604b3313d46e552bc`

Length: 909 characters.

```text
Use the canonical reference image as the exact visual anchor. Preserve the same adult Chinese cultivator, costume, pavilion, mountains, waterfall, composition, and subdued blue-white-gold dawn palette.

Preserve the reference's soft matte material response: natural skin texture with restrained facial highlights, low-gloss soft-satin fabric, diffuse weathered wood, muted rocks and architecture, and only small localized reflections on jade and metal. Do not brighten or polish the scene.

One slow smooth push-in only. She remains almost still: natural breathing, one subtle blink, and a gentle breeze moving a few hair strands and sleeve edges. Keep identity, composition, lighting, and environment stable throughout.

One character only. No scene change, no style shift, no glossy/waxy/plastic skin, no harsh specular patches, no glowing mist, no shiny wood, no camera pan, tilt, orbit, or handheld shake.
```

Compared with X1B, X1C removes repeated face/costume/environment reconstruction language and treats the improved still as authoritative visual state. The experiment variable is therefore the new accepted static anchor plus the concise reference-first prompt architecture; model, duration, resolution, camera motion, and micro-motion remain fixed.
