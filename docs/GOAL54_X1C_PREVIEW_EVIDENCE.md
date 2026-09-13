# Goal 54 — X1C Preview Evidence

Date: 2026-09-13
Status: **TECHNICAL VERIFIED / VISUAL UNVERIFIED**

## Candidate source

X1C was dispatched after the Owner-selected `XIANXIA_ANCHOR_V2` had been byte-level bound locally.

- source HEAD before provider execution: `d6246055955845faafad2a560b63ca36125383df`
- anchor path: `D:\Story Auto\evidence\goal54\xianxia\xianxia_anchor_v2.png`
- anchor SHA-256: `569030979570518ca7ed7fedd9499065f499b11977eb5131ce436dad5e5ca42c`
- prompt path: `D:\Story Auto\evidence\goal54\xianxia\x1c_prompt.txt`
- prompt SHA-256: `ed71f3e6edbee061427b9efc1fa265dd4bddd6637adaf3d604b3313d46e552bc`
- prompt length: 909 characters
- model: `seedance-2-fast-i2v`
- mode: I2V
- duration: 4 s
- resolution: 480p
- aspect ratio: 16:9

## Durable provider identity

The initial X1C call dispatched exactly once and then returned a transient wait state. Recovery reused the same durable job; no second `make_video` call was issued.

- recipe: `X1C`
- clientRef: `story-auto-g54-f94a06802ffaea0a883f6511db981d0542f73c3361db9038`
- identity SHA-256: `f94a06802ffaea0a883f6511db981d0542f73c3361db903811586670e88290c3`
- jobId: `cos_leYmn4yuIWZosURXvTRbUo:39c7c363-51be-46b1-87c1-661b8ddfffa1`
- genId: `g_1e1719f8fdf634aa8f064d90`
- provider execution state: `done`
- terminal research state: `PREVIEW_READY`

The recovery path was the existing `resume` action only. It polled the same `jobId`; it did not redispatch.

## Provider consequence evidence

Read-only preflight before dispatch reported:

- available balance before X1C: 90 Credits
- Fast I2V 4 s / 480p estimate: 44 Credits

At `PREVIEW_READY`, Elyum reported:

- `unlockCredits=20`

No Keep or Kill has been executed for X1C. Treat the locked preview as provider-hold/research evidence, not as proof of final spend. Do not infer a post-preview available balance from this record unless a separate read-only account observation is captured.

## Local preview provenance

Locked preview:

`D:\Story Auto\evidence\goal54\xianxia\x1c_locked_preview.mp4`

SHA-256:

`011ddec32d66f4db2ac549669c80cfaf3f428c05c4132567b06445f4a50f1b66`

Technical media probe:

- codec: H.264
- dimensions: 836x480
- frame rate: 24 fps
- frames: 97
- duration: 4.041667 s

Review derivatives:

- X1C contact sheet: `D:\Story Auto\evidence\goal54\xianxia\x1c_contact_sheet.png`
- contact sheet SHA-256: `a272dd60a96eadbfde1a0fcfbfaff5e47aa3870f973e99f9f5217d95d82b67e1`
- matched X1B | X1C comparison: `D:\Story Auto\evidence\goal54\xianxia\x1b_vs_x1c_compare.png`
- comparison SHA-256: `2665c15d4c68d24468797ad22c9e1b0964e86b317e6c2459e752bda57a2a10c7`

## Acceptance state

Technical acquisition/provenance is verified. Visual acceptance is deliberately **UNVERIFIED** until the Owner reviews the actual X1C motion/render surface.

The visual oracle must judge at minimum:

- matte/natural skin remains at least as acceptable as Anchor V2;
- environment, wood, fabric and scenic materials do not regain excessive brightness/gloss;
- identity and costume remain coherent;
- slow push-in and micro-motion are natural;
- no scene/style drift or distracting deformation.

Until that review passes:

- do not Keep X1C;
- do not Kill X1C solely for cleanup;
- do not run X2 continuity;
- do not promote Prompt Compiler V2;
- do not change production routing.
