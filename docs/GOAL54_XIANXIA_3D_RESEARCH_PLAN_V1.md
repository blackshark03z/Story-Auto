# Goal 54 — Xianxia 3D Research Plan V1

Date: 2026-09-13

Status: **ACCEPTED RESEARCH CONTRACT**

Decision: `docs/decisions/0003-goal54-xianxia-3d-research-branch.md`

## Purpose

Determine whether Story Auto can produce a repeatable high-quality **3D Chinese
xianxia/donghua** sequence with stable character identity, costume, environment,
camera intent and simple subject motion while keeping Elyum/Seedance spend
bounded and recoverable.

This research optimizes for a repeatable method, not one unusually beautiful
lucky generation.

## Starting runtime truth

- R1 provider/recovery research was explicitly Kept by the Owner.
- A 2026-09-13 read-only Elyum account preflight reports **130 Credits** balance,
  **1/1 kill remaining**, and Fast I2V 4 s estimate **44 Credits**.
- The balance change from 150 to 130 matches R1's provider-reported
  `unlockCredits=20`; no kill allowance was consumed.
- BytePlus remains the production Full Video baseline/fallback. This branch does
  not change production routing.

## Canonical visual anchor

Create exactly one new canonical anchor with GPT Image after this plan is
committed. Do not continue producing ad-hoc variations before X1.

### Character — `XIANXIA_F01`

Stable identity markers:

- young adult Chinese female cultivator;
- refined oval face, calm expression, dark-brown eyes;
- long black hair in a half-up style;
- one silver-blue floral hairpin with restrained hanging ornaments;
- white and pale-blue layered xianxia hanfu;
- teal/blue-green waist sash;
- one jade pendant and restrained silver drop earrings.

Do not add scars, tattoos, modern accessories, elaborate crowns, multiple
necklaces or rapidly changing costume details in V1.

### Environment — `XIANXIA_ENV_PAVILION_01`

Stable scene anchors:

- ancient Chinese wooden mountain pavilion;
- misty layered peaks and one visible waterfall;
- one distant traditional pavilion/pagoda;
- soft dawn light with blue-white-gold palette;
- restrained drifting mist/light particles;
- no readable calligraphy, banners, subtitles or decorative text.

Readable text is excluded because it is unrelated to the cinematic/continuity
question and creates a needless failure variable.

### Style lock

Required:

- high-quality 3D donghua / Chinese xianxia visual language;
- stylized semi-real CG with **soft-matte skin/fabric/material response**, diffuse lighting and restrained specular highlights;
- elegant, airy and restrained rather than glossy/plastic game-UI/fantasy spectacle.

Reject:

- 2D anime drift;
- photoreal live-action drift;
- Western medieval/elf/fairy visual language;
- cyberpunk/sci-fi elements;
- sexualized redesign or material costume change.

### Anchor framing

The single canonical anchor should be 16:9, medium-to-medium-full framing, with
face, hair ornament, upper costume, waist sash and enough pavilion visible to act
as both character and environment evidence.

Store the canonical image outside Git under:

`D:\Story Auto\evidence\goal54\xianxia\xianxia_f01_anchor.png`

Record its SHA-256 and generation identity in Git evidence. The image bytes stay
outside source control.

Canonical anchor local evidence is now established:

- GPT Image generation: `5eb96ca5-da11-4d7e-b615-7e1e9fef1726`;
- local path: `D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_f01_anchor.png`;
- normalized size: 1280x720;
- SHA-256: `d8a48a3e725b8511250f84506458bcdf2d13e4f2e9a73cabd8c3f4f5eb2ae96b`;
- source checkpoint before live X1 work: `1ca395254309de80b182fbed3566cf07de1ee016`.

This provenance binding satisfies the CADS acceptance-surface provenance rule for
using the anchor as an X1 input candidate. Any later local replacement or hash
mismatch makes the affected evidence `UNVERIFIED` until rebound.

### Canonical anchor candidate selected — provenance pending local import

The selected GPT Image source is generation
`5eb96ca5-da11-4d7e-b615-7e1e9fef1726` (`xianxia_maiden_over_the_misty_mountains`).
A deterministic crop/resize was produced from those exact source bytes to remove
readable side banners while preserving the same character/environment candidate.
Canonical candidate properties:

- target size: `1280x720` PNG;
- expected SHA-256:
  `d8a48a3e725b8511250f84506458bcdf2d13e4f2e9a73cabd8c3f4f5eb2ae96b`;
- intended local acceptance/evidence path:
  `D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_f01_anchor.png`.

Under CADS Acceptance Surface Provenance, this candidate is **not yet admissible
for X1 dispatch** until the local file at the intended path is verified to have
that exact SHA-256. A chat-visible image, clipboard image, filename or visual
similarity alone cannot substitute for byte-level candidate binding.

## Experiment ledger and artifact boundary

Use a new ledger, separate from R1:

`D:\Story Auto\evidence\goal54\xianxia\elyum_xianxia_v1.json`

Provider previews, kept originals, extracted continuity frames and contact sheets
also stay under `D:\Story Auto\evidence\goal54\xianxia\` and outside Git.

Every experiment record must preserve recipe ID, canonical input SHA-256, prompt
fingerprint, provider/model/settings, durable `clientRef`/`jobId`, live estimate,
actual unlock price/final Credit consequence, output hash/technical metadata and
manual rubric/critical flags.

### Acceptance-surface provenance envelope

Before any X1/X2/X3 preview or local file may support a PASS/Owner-review claim,
record enough provenance to reconstruct the observed surface:

- exact Story Auto source HEAD used for the adapter/runner;
- recipe ID + prompt fingerprint + model/settings;
- input/reference file SHA-256 and canonical evidence path;
- research ledger path and durable `clientRef`/provider `jobId`/`genId` when
  available;
- provider surface state (`locked preview`, `kept original`, etc.);
- acquired local artifact SHA-256 + technical metadata;
- material account/config evidence such as live estimate/balance when it affects
  the claim;
- which concrete artifact/surface the human rubric evaluated.

If a displayed/uploaded/reviewed artifact cannot be tied back to this envelope,
its visual evidence is `UNVERIFIED`. A locked preview can prove preview quality;
it does not automatically prove a later kept original or integrated Story Auto
render without lineage/equivalence evidence.

## Shot sequence

### X1 — Style Lock + Camera

Purpose: prove that one xianxia anchor survives I2V while the model follows one
simple camera instruction.

Settings:

- model: Seedance 2 Fast I2V;
- duration: 4 s;
- resolution: 480p;
- aspect ratio: 16:9;
- audio: off;
- framing: `MEDIUM_EYE_LEVEL` with slight three-quarter pose inherited from anchor;
- camera: `SLOW_PUSH_IN`;
- subject: `HOLD_WITH_MICROMOTION` only;
- environment: unchanged.

Allowed subject motion: breathing, subtle blink, small hair/sleeve response to
wind. Do not combine X1 with a deliberate head turn, hand gesture or aura effect.

Exact X1 prompt V1 is frozen before dispatch and mirrored locally at
`D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_prompt.txt` (UTF-8, 1258 chars),
SHA-256 `e28c57c545a1c606c13df1637664ace5c9718304ca85bea3afcfa70d563592da`:

```text
Same young adult Chinese female cultivator from the reference image: refined oval face, dark-brown eyes, long black half-up hair, one silver-blue floral hairpin with restrained hanging ornaments, white and pale-blue layered xianxia hanfu, teal waist sash, one jade pendant, restrained silver drop earrings. Preserve the same ancient Chinese wooden mountain pavilion, misty layered peaks, one visible waterfall, one distant traditional pavilion, and soft dawn blue-white-gold lighting. High-quality 3D Chinese xianxia/donghua, stylized semi-real polished CG. Medium eye-level framing with the slight three-quarter pose inherited from the reference. The camera performs one slow smooth push-in only. The subject remains mostly still with natural breathing, one subtle blink, and slight hair and sleeve movement from a gentle breeze. Preserve exact identity, hairstyle, hairpin, costume palette, jade, pavilion layout, mountains, waterfall, and lighting. No deliberate head turn, no hand gesture, no aura or spell effect, no scene change, no extra characters, no 2D anime drift, no photoreal live-action drift, no Western fantasy elements, no pan, no tilt, no orbit, no handheld shake, no cut, no deformed face, hands, body, hair, or fabric. Silent visual only.
```

A prompt-file hash mismatch blocks dispatch until provenance is rebound.

X1 is the **only authorized next provider dispatch** after this plan is committed.
It requires a fresh live estimate and hard bound of 44 Credits unless the live
estimate is lower. Preview creation may hold Credits; Keep/Kill is not automatic.

### X2 — Shot-to-shot Continuity

Precondition: X1 scores at least 8/10, has no critical failure, is explicitly
Kept, and a clean frame can be extracted from the kept original.

Input: a selected clean late/representative frame from X1, not the original GPT
Image anchor and not a watermarked locked preview.

Settings remain Fast I2V / 4 s / 480p / 16:9 / audio off.

Change exactly one dominant motion variable:

- camera: `LOCKED`;
- subject: `SLOW_HEAD_TURN` toward camera, then hold.

Everything else — identity, hair ornament, costume palette, pavilion layout,
lighting language and style — must remain continuous with X1.

X2 is not pre-authorized by this plan. Re-read balance/estimate and preserve the
Owner consequence boundary after X1.

### X3 — Controlled Spiritual Motion

Precondition: X2 passes continuity QA and current balance supports another bounded
preview.

Input: clean selected frame from kept X2.

Change exactly one new semantic variable:

- framing: medium shot if the continuity frame supports it;
- camera: `LOCKED`;
- subject: slowly raises one hand;
- VFX: one small pale-blue spiritual aura gathering around the raised hand.

VFX must remain subtle and must not obscure the face, hands or costume. No sword
fight, flying weapons, explosion, teleport, multi-person interaction or scene cut.

X3 is conditional and requires a new budget decision. It is not automatically
queued after X2.

### Optional X4 — Seedance 2.5 Reference A/B

Only after Fast-I2V behavior is understood. Use the same accepted recipe/input
and change only the model/reference mechanism to measure whether 2.5 Reference
materially improves identity/continuity. Do not use X4 as a fallback for a bad
prompt or bad anchor.

## Prompt compiler blocks

Every xianxia shot prompt must be built in this order:

1. **Identity block** — same named research character and immutable markers.
2. **Environment block** — same pavilion and fixed scene anchors.
3. **Style block** — 3D Chinese xianxia/donghua, semi-real **soft-matte CG** with diffuse light, gentle atmospheric softness and restrained specular response.
4. **One action block** — exactly one dominant subject action.
5. **One camera block** — exactly one dominant camera behavior.
6. **Continuity block** — preserve face, hair ornament, costume palette, jade,
   pavilion layout and lighting.
7. **Negative block** — only known relevant failures.

Do not fill prompts with camera-brand, film-stock, 8K or lens-brand ornament
until Seedance evidence shows those tokens improve a measurable outcome.

## Acceptance rubric — 10 points

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Xianxia/style fidelity | wrong domain/style | recognizable but mixed/drifting | clearly polished 3D Chinese xianxia |
| Identity/costume stability | material replacement | minor drift | stable face/hair ornament/costume |
| Environment continuity | replacement/layout break | minor drift | stable pavilion/mountains/waterfall |
| Camera/action compliance | wrong/unreadable | partial | clearly follows the one requested behavior |
| Anatomy/fabric/hair/VFX stability | severe artifact | visible tolerable issue | clean/readable motion |

Pass threshold: **>= 8/10 and no critical failure**.

Critical failures:

- identity replacement;
- material hairstyle/hair-ornament or costume redesign;
- Western-fantasy/2D/live-action style replacement;
- unexpected scene replacement or hard cut;
- severe hand/face/body deformation;
- requested camera direction is opposite or chaotic;
- VFX obscures/breaks subject anatomy;
- provider result cannot be tied to the durable request/job identity.

A single passing X1/X2/X3 remains `RESEARCH_CANDIDATE`. Promotion toward Story
Auto planning still requires repeatability evidence; insufficient free Credits
must stop the research rather than weaken the acceptance rule.

## Credit and consequence policy

Starting verified balance for this branch: **130 Credits**.

Current Fast I2V 4 s read-only estimate: **44 Credits**. Re-estimate immediately
before every dispatch; this is not a permanent constant.

Rules:

1. run only one provider generation at a time;
2. never auto-start X2/X3;
3. never auto-Keep or auto-Kill;
4. Keep only after rubric review and explicit Owner approval, using provider
   `unlockCredits` as the actual known consequence;
5. do not spend the sole kill allowance merely to tidy research history;
6. if estimate/balance changes unexpectedly, block before dispatch;
7. no 720p/1080p testing until the method passes at 480p.

## Execution order

1. Commit/push this research contract.
2. Generate the one canonical GPT Image anchor in one image-generation step.
3. Persist anchor outside Git and record SHA-256/generation identity in evidence.
4. Read-only Elyum balance + X1 estimate.
5. Upload/reuse anchor and dispatch only X1 with durable `clientRef`.
6. Recover the same job to locked preview.
7. Acquire preview locally and perform technical + human rubric QA.
8. Stop for explicit Keep/Kill decision.
9. Only after a kept X1: extract a clean continuity frame and plan X2.
10. X3/X4 remain conditional on evidence and budget.

## X1 runtime evidence — pending visual verdict

Candidate source HEAD for dispatch:
`b1c3ea61fb356939f663137ae71f6f35ac8b21b7`.

Bound inputs:

- anchor path: `D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_f01_anchor.png`;
- anchor SHA-256: `d8a48a3e725b8511250f84506458bcdf2d13e4f2e9a73cabd8c3f4f5eb2ae96b`;
- prompt path: `D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_prompt.txt`;
- prompt SHA-256: `e28c57c545a1c606c13df1637664ace5c9718304ca85bea3afcfa70d563592da`;
- model/settings: Seedance 2 Fast I2V, 4 s, 480p, 16:9, audio off;
- live balance before dispatch: 130 Credits;
- live estimate before dispatch: 44 Credits.

Durable provider identity:

- clientRef: `story-auto-g54-3604b3b68a1483f2692154ddd1f0a46e326356c37090aad6`;
- jobId: `cos_leYmn4yuIWZosURXvTRbUo:7e7856b2-3d90-42ff-ae0b-7a2664510d62`;
- genId: `g_c94da17e6dfeb2f8814a7648`.

The initial wait and one explicit resume both returned transient-unavailable, but
all recovery stayed on the same durable job. A subsequent resume reached
`PREVIEW_READY`; provider execution state is `done`, preview count is one, and
reported `unlockCredits=20`. There was no second generation dispatch.

Acceptance-surface provenance:

- local locked preview:
  `D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_locked_preview.mp4`;
- preview SHA-256:
  `b89e5b057a8a83534abb26d73d3e6ac6f7404a151f7c617496839f6a0baf48eb`;
- technical media: H.264, 836x480, 24 fps, 97 frames, 4.041667 s;
- contact sheet:
  `D:\\Story Auto\\evidence\\goal54\\xianxia\\x1_contact_sheet.png`;
- contact-sheet SHA-256:
  `03589216d946f187b6792974fceae3738b7ff74188ab09e8829630883c3ca10f`.

These artifacts are the exact Owner-review surface for X1. Technical validity and
provenance are verified.

### X1 Owner visual verdict — 2026-09-13

Owner review of the provenance-bound locked preview found the overall color/material
response too glossy: skin and scene objects appear somewhat shiny/plastic. The
requested correction is to **reduce gloss/specular response and increase softness**
while preserving identity, scene, framing and camera behavior.

Therefore X1 is `PARTIAL_FAIL_STYLE_SURFACE`:

- provider transport/recovery/provenance: PASS;
- identity/scene/camera baseline: useful evidence, not rejected;
- style-surface acceptance: FAIL for V1 target;
- Keep: **not authorized**;
- Kill: **not required**; preserve the locked preview as evidence;
- X2: remains blocked because X1 is not an accepted style anchor.

The next authorized provider experiment is **X1b Matte-Soft Retry**, changing only
the material/lighting style block. X1b must reuse the exact canonical anchor,
Fast-I2V 4 s / 480p / 16:9 / audio-off settings, slow push-in and micro-motion.
No continuity, head-turn, hand action, aura or other semantic variable may be
introduced in X1b.

#### X1b exact prompt V1

Local mirror: `D:\\Story Auto\\evidence\\goal54\\xianxia\\x1b_prompt.txt`

SHA-256: `a0886dfee4f36c4eb5f1d82c477d5545e1a8573fb1735f26b6d6a7d5d5d04cc9`

```text
Same young adult Chinese female cultivator from the canonical reference image: refined oval face, dark-brown eyes, long black half-up hair, one silver-blue floral hairpin with restrained hanging ornaments, white and pale-blue layered xianxia hanfu, teal waist sash, one jade pendant, restrained silver drop earrings. Preserve the same ancient Chinese wooden mountain pavilion, misty layered peaks, one visible waterfall, one distant traditional pavilion, and the same soft dawn blue-white-gold palette.

High-quality 3D Chinese xianxia/donghua with a soft-matte, airy and elegant material response. Use soft diffuse lighting, gentle atmospheric softness, matte natural skin, matte silk fabric, soft wood response and restrained specular highlights on skin, hair, fabric, wood, jade and ornaments. Preserve subtle depth and clarity without a waxy, wet, plastic or metallic sheen. Avoid harsh contrast, hard highlights, glossy fabric, glossy wood, overly reflective objects and overly sharp game-CG rendering.

Keep the same medium eye-level framing and slight three-quarter pose inherited from the reference. The camera performs one slow smooth push-in only. The subject remains mostly still with natural breathing, one subtle blink, and slight hair and sleeve movement from a gentle breeze.

Preserve exact identity, hairstyle, hairpin, costume palette, jade, pavilion layout, mountains, waterfall and lighting composition. No deliberate head turn, no hand gesture, no aura or spell effect, no scene change, no extra characters, no 2D anime drift, no photoreal live-action drift, no Western fantasy elements, no pan, no tilt, no orbit, no handheld shake, no cut, no deformed face, hands, body, hair or fabric. Silent visual only.
```

The intended A/B delta from X1 is only surface/light response: softer diffuse
illumination, matte skin/fabric/wood and restrained specular highlights. Identity,
environment, camera and subject-motion intent are held constant.

## Non-goals for V1

- multiple named characters;
- combat choreography;
- flying swords or complex spell choreography;
- dialogue/lip-sync;
- camera orbit/whip-pan/handheld;
- multiple actions in one shot;
- production routing changes;
- generalized cinematic prompt library;
- production UI work.
