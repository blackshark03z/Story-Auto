# Goal 54 — Xianxia Anchor V2 Checkpoint

Date: 2026-09-13
Status: **TEMPORARY RESEARCH CHECKPOINT**

## Decision

Before spending another Seedance preview on prompt-only correction, create one new canonical still image with GPT Image and make the desired material response correct at the source frame.

Target workflow:

`Visual Constitution -> GPT Image canonical anchor -> short Seedance I2V shot prompt -> kept-frame continuity`

Do not promote this checkpoint into production routing. It is a research method for Goal 54 only.

## Why this checkpoint exists

X1 and X1b proved the Elyum/Seedance transport/recovery path and produced usable camera/continuity evidence, but the Owner's visual oracle identified excessive glossy/plastic material response. X1b reduced global highlight fraction, yet the research still asks Seedance to preserve an already-polished anchor while simultaneously changing its material language. That is an avoidable conflict.

The attached long-form prompt supplied by the Owner is treated as a **Visual Constitution**, not as a direct Seedance shot prompt. Its useful responsibilities are identity, hair/jewelry, costume, environment, skin/material response and lighting. Its body/leg/bust/full-body composition sections are not copied into the current medium-shot I2V prompt unless the shot actually needs them.

## Anchor V2 target

Create exactly one image candidate, `XIANXIA_ANCHOR_V2`, preserving the accepted research character/environment identity while changing material/lighting intent at the still-image stage.

Required visual target:

- mature Chinese 3D donghua/xianxia heroine;
- same long black half-up hair, silver-blue floral hairpin, white/pale-blue hanfu, teal waist sash and jade pendant identity language;
- same ancient wooden mountain pavilion, layered misty peaks, waterfall and distant pavilion;
- 16:9 medium-to-medium-full composition suitable for later I2V;
- natural matte skin with subtle microtexture and gentle subsurface softness;
- broad low-intensity facial highlights, no wet/oily/waxy/plastic sheen;
- soft-satin silk rather than glossy synthetic fabric;
- diffuse wooden surfaces;
- antique gold and jade may retain small localized controlled reflections;
- soft diffuse blue-white-gold dawn lighting;
- gentle atmospheric depth; no harsh HDR/game-CGI look;
- no text, logo, watermark, UI or readable calligraphy.

## Prompt architecture rule

GPT Image may receive the richer Visual Constitution because it owns static visual design.

Seedance should receive a compact shot instruction only:

1. reference lock;
2. one material/style delta only if still needed;
3. one subject-motion block;
4. one camera block;
5. continuity lock;
6. a short critical-negative block.

Avoid repeating anatomy/costume/background specifications that the accepted reference image already proves unless a shot materially changes them.

## Next experiment after Anchor V2

Do not run X2 yet.

After Anchor V2 is visually accepted and locally provenance-bound, run one new Fast-I2V 4 s / 480p comparison candidate using the concise reference-first prompt architecture. Preserve the previous slow push-in + micro-motion recipe so the primary experiment variable is the improved static anchor and shorter prompt architecture.

The provider consequence boundary remains unchanged: live estimate/balance first, one durable clientRef/jobId, no blind resubmit, no automatic Keep/Kill.

## Acceptance

Anchor V2 must already look correct as a still image before video generation:

- skin/material softness acceptable to Owner;
- no excessive gloss/plastic/waxy appearance;
- character identity and costume coherent;
- environment/style clearly 3D Chinese xianxia/donghua;
- composition viable for the intended slow-push-in shot.

If the still image fails these conditions, revise the still-image prompt/reference before spending another video preview.

## Owner-selected Anchor V2 candidate

The Owner accepted the latest still-image direction for continuation after iterative reduction of skin gloss, excessive whitening, and environmental/object shine. The selected chat-visible candidate is 1672x941 PNG and is frozen by expected SHA-256:

`569030979570518ca7ed7fedd9499065f499b11977eb5131ce436dad5e5ca42c`

Intended local evidence path:

`D:\\Story Auto\\evidence\\goal54\\xianxia\\xianxia_anchor_v2.png`

CADS acceptance-surface provenance is now satisfied for the still: exact bytes are present locally at the intended path, dimensions are 1672x941, and SHA-256 matches `569030979570518ca7ed7fedd9499065f499b11977eb5131ce436dad5e5ca42c`. Visual similarity/filename were not used as substitutes for the byte-level binding.

This candidate is intentionally not re-styled by Seedance. X1C must preserve its existing matte skin, restrained highlights, subdued scene brightness, diffuse weathered wood, muted mountain/pavilion materials, and localized jade/metal reflections.
