# Hybrid Visual — Canonical CUJ / Product Flow Acceptance

Date: 2026-09-16
Status: PRODUCT_FLOW_ACCEPTED / QUALITY_DEFERRED

## Accepted user journey

`New video -> Hybrid Visual -> prepare canonical timing/story plan -> Opening Builder -> import exact opening slots -> Continue -> automatic body IMAGE acquisition -> semantic stock or image fallback -> technical quality gate -> canonical final video`

The opening remains approximately 15–20 seconds and is decomposed into stable 5–10 second slots. Manual external generation is a supported product path: prompts are copied from Story Auto and imported results bind to slot IDs, never guessed filenames.

## Canonical execution route

Hybrid now runs under the existing six-stage coordinator:

`SOURCE -> TIMING -> PLAN -> VISUALS -> QUALITY -> RENDER`

Mode-specific behavior:

- PLAN: prepares/approves canonical story state, Opening Builder and Hybrid body plan.
- VISUALS: blocks only for missing owner opening clips or required provider connection; body images use the existing Flow generation engine; stock may resolve through Pexels or fall back to generated images.
- QUALITY: `TECHNICAL_ONLY_V1`, with exact input-hash binding.
- RENDER: mixed silent visual timeline feeds the existing master compositor and promotes to canonical `output/final.mp4` + `output/final_manifest.json`.

Narration/alignment is still the master clock. Subtitles/waveform/BGM remain continuous and visual source audio is muted by contract.

## Recovery and stale-state guarantees

- completed opening/body work survives Continue;
- selected/generated body images are SHA-bound back to exact Hybrid slots;
- historical projects without explicit CUJ activation remain deferred;
- replacing an Opening/body input after final invalidates quality/final bindings;
- an old `final.mp4` cannot make the project report COMPLETE after inputs change.

## Product activation

Hybrid Visual is selectable in the New video wizard on current main. New UI-created Hybrid projects snapshot `hybrid_visual.cuj_enabled=true`. Full Image remains the default.

## Verification evidence

Post-promotion focused/broad qualification: **76 tests PASS**:

- Opening Builder: 7;
- semantic Pexels/body foundation: 7;
- mixed compositor: 2;
- canonical Hybrid CUJ: 4, including 2 real Playwright browser tests;
- mode/release guards: 8;
- Full Image regression: 7;
- Render regression: 19;
- Application regression: 18;
- Goal 54 product-surface regression: 4.

Browser evidence proves both:

1. New video wizard exposes an enabled `HYBRID VISUAL` choice.
2. Existing prepared Hybrid project: `Import opening clips -> Continue production -> COMPLETE -> Open final video`.

Python compile, JavaScript syntax and repository security gates PASS; `YOUTUBE_AUTO_RUNTIME_IMPORTS=0`.

Playwright Chromium was installed only as a local test dependency; this does not alter Story Auto runtime/provider policy.

## Explicitly deferred quality work

The following are not part of this acceptance and remain future quality iterations:

- better image motion/effects and transitions;
- richer semantic stock matching and stock selection aesthetics;
- opening motion/acting quality;
- pacing and source-change rhythm;
- subtitle/waveform visual styling;
- optional opening API acquisition;
- broader live-provider quality UAT.

These items may improve output quality without reopening the accepted Product Journey contract unless they cause a workflow regression.
