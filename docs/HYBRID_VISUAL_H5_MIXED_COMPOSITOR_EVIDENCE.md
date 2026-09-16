# Hybrid Visual H5 — mixed compositor evidence

Date: 2026-09-16
Status: ENGINEERING_COMPLETE / MIXED_PREVIEW_PROVED / PRODUCT_ACCEPTANCE_PENDING / RELEASE_DISABLED

## Goal

Prove the V1 Hybrid Visual composition path without changing release availability:

`Opening Builder video -> image motion/effects -> Pexels stock video or image fallback -> image motion/effects -> ... -> master narration end`

Audio ownership must remain unchanged: narration is canonical, subtitles derive only from canonical alignment, waveform derives from the same narration stream, BGM remains independent, and all visual-source audio is muted/ignored.

## Implementation

### Body image binding

`adopt_hybrid_body_image(...)` binds explicit local images to:

- ordinary `IMAGE` body slots; or
- `STOCK_VIDEO` slots as an explicit image fallback.

The project stores a project-relative local source, SHA-256, dimensions, original filename and replacement history. A stock fallback does not rewrite the semantic stock slot; it remains an explicit fallback asset.

### Mixed preview readiness

`hybrid_preview_readiness(...)` fails closed until:

- every Opening Builder slot is READY with a valid normalized silent clip;
- a Hybrid body plan exists;
- every IMAGE slot has a valid bound image;
- every STOCK_VIDEO slot has either a valid normalized Pexels video or a valid image fallback;
- canonical alignment exists.

### Mixed visual compilation

`render_hybrid_preview(...)` builds one exact visual sequence:

- Opening Builder READY clips are reused directly and re-probed to reject any audio stream;
- body images compile through the existing deterministic image compiler with restrained motion mapping;
- READY Pexels videos reuse the H4 normalized silent local asset;
- stock fallback images compile with restrained slow-push motion;
- all boundaries are exact CUTs in this foundation so source-type changes cannot shift the master timeline;
- the visual end must exactly equal canonical `alignment.duration_seconds` before composition.

### Master-track composition

The preview reuses Story Auto's existing compositor instead of adding a Hybrid-specific audio pipeline:

- subtitles are rebuilt from canonical alignment;
- narration comes from `alignment.audio_path`;
- waveform uses FFmpeg `showwaves` over canonical narration;
- optional BGM follows existing render settings;
- visual clips are required to be silent;
- final preview is explicitly marked `release_activation=BLOCKED_UNTIL_E2E_PRODUCT_ACCEPTANCE`.

Artifacts:

- `output/hybrid_preview.mp4`
- `output/hybrid_preview_manifest.json`
- `output/hybrid_subtitles.srt`
- `output/hybrid_subtitles.ass`

The development preview never writes `output/final.mp4`.

## Product surface

Existing/development `hybrid_hook` projects now expose:

- import/replace image on IMAGE slots;
- import/replace image fallback on stock slots;
- one-slot Pexels resolution where configured;
- readiness count for missing visual assets;
- `Render mixed preview` only when every visual slot is satisfiable;
- inline mixed preview playback.

The mode remains `FEATURE_NOT_AVAILABLE` for release/new-project use.

## FFmpeg proof

Focused integration suite: `tests/test_hybrid_visual_mixed_render.py` — 2/2 PASS.

The synthetic proof uses:

- 36.0 s canonical narration audio;
- two 7.5 s Opening Builder clips whose source files contain audio, then Opening Builder strips it;
- three 4 s IMAGE slots;
- one 5 s Pexels STOCK_VIDEO slot whose source contains audio, then H4 normalization strips it;
- one final 4 s IMAGE slot;
- real subtitle generation and waveform composition.

Observed assertions:

- exact visual source order includes `OPENING_VIDEO -> IMAGE -> STOCK_VIDEO -> IMAGE`;
- adjacent slot end/start timestamps match exactly;
- final visual endpoint is 36.0 s;
- final preview duration matches 36.0 s within compositor tolerance;
- final preview contains one audio stream;
- narration SHA in preview manifest equals canonical narration SHA;
- waveform is enabled and derives from canonical narration;
- SRT and ASS artifacts exist;
- `output/final.mp4` is absent.

A second proof replaces stock video with an explicit image fallback and reaches READY without a provider call.

## Real-asset local UAT checkpoint — 2026-09-16

A reproducible local UAT harness now exists at `tools/hybrid_visual_uat.py`. It deliberately uses already-accepted Xianxia evidence assets from Goal 54 rather than synthetic color cards:

- `x1c_kept_clean.mp4`, `x2_kept_clean.mp4`, `x3_kept_clean.mp4` feed two 7.5 s Opening Builder slots after local concatenation;
- `xianxia_anchor_v2.png`, `x2_continuity_frame.png`, and `x3_continuity_frame.png` feed body IMAGE slots and the explicit stock fallback;
- Windows local `Microsoft Zira Desktop` produces a provider-free narration WAV because the post-SSD Kokoro probe currently reports `KOKORO_MODEL_NOT_FOUND`; Kokoro recovery is tracked as independent environment drift, not an H5 blocker.

Durable local runtime evidence:

- runtime: `../evidence/hybrid_visual_h5_uat/runtime`
- project: `prj_hybrid_xianxia_uat`
- preview: `../evidence/hybrid_visual_h5_uat/runtime/projects/prj_hybrid_xianxia_uat/output/hybrid_preview.mp4`
- preview SHA-256: `7aa58eee8a40dfa014d082cdc6bc297f506ae1627b4cd99c314de791f78851dd`
- duration: `42.583333` s
- narration SHA-256: `c83c9a7a9db3f5a488179feee63e665bb2c666cb47aa3ce160c6e4daa7bad276`
- timeline source kinds: `OPENING_VIDEO, OPENING_VIDEO, IMAGE, IMAGE, IMAGE, STOCK_IMAGE_FALLBACK, IMAGE`
- visual audio contract: `MUTED_BY_CONTRACT`
- waveform: enabled
- release activation: `BLOCKED_UNTIL_E2E_PRODUCT_ACCEPTANCE`

Application-level projection over that exact runtime reports:

- `pipeline_status=FEATURE_NOT_AVAILABLE`
- `opening_ready=true`
- `body_slots=5`
- `hybrid_preview.preview_ready=true`
- preview readiness `missing=[]`

This is a **machine-observable real-asset UAT PASS** for the manual/fallback Hybrid journey. It is intentionally not owner visual acceptance: a human still needs to watch the preview and decide whether motion, source boundaries, subtitle placement, waveform placement and overall visual quality are acceptable before promotion into the canonical final-render path.

## What this does not claim

This is not yet Product Acceptance or release qualification for Hybrid Visual. Remaining gates:

1. Run one owner-visible exact E2E UAT on a representative story/project, including real opening clips and at least one real Pexels asset or deliberate fallback.
2. Inspect visual quality, subtitle/waveform placement and source-change boundaries in the resulting preview.
3. Polish any ordinary-user workflow gaps exposed by that UAT.
4. Promote the preview recipe into the canonical final render path only after Product Acceptance.
5. Only then consider changing `render_mode_availability("hybrid_hook")`.

H3 opening API acquisition remains optional; manual Opening Builder already feeds the same H5 contract and does not block Product Acceptance.
