# Frozen Product Design — Story Auto V1

Status: **FROZEN**  
Frozen: **2026-08-12**

## 1. Product outcome

Story Auto turns a valid `content.md` into a cinematic, long-form YouTube storytelling video and a small publishing package. It is a separate tool from YouTube Auto.

## 2. Primary input

`content.md` with a required, non-empty `## Narration` section. Narration text is preserved; the parser may expose optional metadata sections but must not silently treat an arbitrary whole document as narration.

## 3. Visual modes

### `hybrid_hook`

- default video hook target: 55 seconds, configurable;
- body: generated images with restrained motion;
- planner may propose video motion spikes;
- operator may change eligible shot media type;
- required hook video is not silently replaced by a still.

### `full_video_ai`

- every final visual shot is `VIDEO / REQUIRED`;
- stills may be reference/keyframe/ingredient assets only;
- unresolved required video blocks production render.

Both modes share one timeline, planning system, generation manager, render resolver, and final composer.

## 4. TTS

Exactly two TTS providers in V1:

- ElevenLabs;
- Typecast.

Reuse/adapt proven provider configuration and mechanics from YouTube Auto. No silent cross-provider fallback. Both normalize into one canonical alignment contract.

## 5. Planning LLM

Gemini API only in V1.

- baseline model: `gemini-3.5-flash`;
- first benchmark candidate: `gemini-3.6-flash`;
- model is configurable and capability-probed; stage code does not hard-code a model ID.

Structured outputs must be validated before acceptance.

## 6. Visual provider

Google Flow is V1 provider for both images and videos. Core contracts stay provider-independent. Flow browser automation uses a dedicated Story Auto profile and is isolated in provider modules.

## 7. Canonical planning chain

```text
voice
→ alignment.json
→ story_timeline.json
→ continuity_bible.json
→ shot_plan.json
→ media_plan.json
→ review_state.json
→ generation_requests.json
→ generation_manifest.json + assets
→ review_state.json
→ render_plan.json
→ audio_plan.json + subtitles
→ final.mp4 + final_manifest.json
→ publishing_package.json + thumbnail
```

`generation_requests.json` separates provider-call instructions from desired media policy. `render_plan.json` separates desired media from the exact selected source used by the final composer.

## 8. Human approval gates

Before large visual generation:

1. approve continuity + shot plan;
2. generate small recurring reference set;
3. approve references;
4. inspect request count/cost estimate where available;
5. explicitly confirm large batch.

Per asset the operator can approve, reject, regenerate, edit prompt, or replace source. Media-type override is only allowed when the mode/media policy permits it.

## 9. Continuity

Characters, locations, props, wardrobe states, time-of-day states, style, reference assets, and adjacency/handoff information are structured data. Prompts are compiled from that state rather than storing continuity only as free-form prompt prose.

## 10. Generation/retry

Every provider request has a stable identity and append-only attempt history. Default automatic attempt budget is 2. Ambiguous timeout is reconciled against known provider/result state before any re-submit. No infinite polling or retry.

## 11. Composition

Every selected image/video/hold source becomes a normalized silent MP4 segment. One common compositor handles ordering, transitions, narration, BGM, subtitles, and final encode.

Generated Flow video audio is muted in V1. Narration is master audio.

## 12. Audio

- narration required;
- subtitles required;
- optional BGM supported;
- BGM is operator-supplied licensed/local media; Story Auto does not source or generate music in V1;
- SFX/ambience automation deferred.

## 13. Output

Default:

- 1920×1080;
- 16:9;
- MP4;
- raw/generated assets retained;
- title + description + generated thumbnail package.

No YouTube upload in V1.

## 14. Concurrency and cost

One active production Flow-generation project at a time per Story Auto profile. Large batches are confirmation-gated; full-video batch is always confirmation-gated.

## 15. UI

CLI/application services are canonical first. A local UI follows only after hybrid runtime proof and must call the same services/contracts.

## 16. Runtime isolation

Story Auto has its own source repo, runtime root, projects, cache/temp/logs/evidence, browser profile, and locks. It never reuses YouTube Auto runtime or imports YouTube Auto modules at runtime.

## 17. Deferred

YouTube upload, extra visual providers, smart routing, native provider audio, automated SFX, cloud queue, database, multi-user, generic timeline editor, plugin system, and fully automated creative QC.
