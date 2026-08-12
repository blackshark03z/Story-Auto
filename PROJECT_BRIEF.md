# Project Brief — Story Auto V1

## Purpose

Turn one `content.md` narration into a high-quality long-form YouTube storytelling video with strong continuity, recoverable generation, explicit human approval points, and two visual production modes.

## Intended operator

A local content-production operator producing original fictional storytelling videos. V1 is optimized for a single operator and one active production-generation project at a time.

## Required input

`content.md` with a non-empty `## Narration` section. Other sections may exist, but narration is the only mandatory creative source in V1.

## Required output

- `final.mp4`, default 1920×1080, 16:9.
- Narration + subtitles.
- Optional user-supplied/licensed BGM mixed under narration.
- Retained raw/generated image/video assets and per-attempt provenance.
- Title + description package.
- Generated thumbnail asset.

## Render modes

### hybrid_hook

- Opening AI video: default 55 seconds, configurable.
- Body: generated stills + restrained motion.
- Planner may propose motion spikes; operator may override media type where mode policy permits.
- Required hook video may not silently fall back to stills.

### full_video_ai

- Every final visual segment is `VIDEO / REQUIRED`.
- Still images are allowed only as references/keyframes/ingredients or review aids.
- Missing required video blocks final production render.

## Human-in-the-loop requirements

The operator must be able to:

- approve continuity/shot plan before a large Flow batch;
- approve recurring character/location/prop reference images;
- inspect generation budget/request count before a large batch;
- approve, reject, regenerate, edit prompt, or replace an individual asset;
- change IMAGE↔VIDEO only when the active mode policy allows it;
- edit final title/description/thumbnail selection.

## Providers

### TTS

- ElevenLabs
- Typecast

Provider selection is required. Cross-provider fallback is **off by default** so a voice cannot change silently mid-project. Existing proven YouTube Auto provider configuration/logic should be ported selectively after inspection rather than re-invented.

### LLM planning

- Provider: Gemini API.
- V1 baseline: `gemini-3.5-flash`.
- First benchmark candidate: `gemini-3.6-flash`.
- Model choice is configuration, not hard-coded stage logic.

### Visual generation

Google Flow is V1 provider for both images and video. Flow-specific UI/browser details live only in `providers/flow/`.

## Audio

- Narration is master audio.
- Source audio from generated Flow video is muted in V1.
- Subtitles are required.
- BGM support is included, but V1 does **not** source or generate music. The operator supplies a licensed/local track.
- SFX/ambience automation is deferred.

## Publishing package

Generate title, description, and thumbnail. YouTube upload is not part of V1.

## Cost and safety guardrails

- Configurable maximum automatic attempts per generation request; default 2.
- No infinite retry loops.
- Large Flow batches require an explicit operator confirmation.
- `full_video_ai` always requires explicit batch confirmation.
- Ambiguous provider timeout must be reconciled against the generation manifest before re-submit.
- One active Flow production-generation project at a time per Story Auto Flow profile.

## Non-goals for V1

- YouTube publishing/upload.
- Multi-user/cloud queue/database.
- Generic NLE/timeline editor.
- Plugin framework.
- Multiple visual-generation providers.
- Automatic music sourcing/generation.
- Native Flow audio mixing.
- Automatic full creative QC without human review.
- Runtime imports from YouTube Auto.

## V1 success definition

Given a valid `content.md` and configured credentials/session, the operator can plan, review, generate, resume, render, and package a 1080p long-form story in either mode, with deterministic planning artifacts, per-request provenance, explicit failure states, bounded provider spend, and no silent fallback that violates the selected mode.
