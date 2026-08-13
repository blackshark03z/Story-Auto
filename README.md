# Story Auto

Story Auto is a local, artifact-first production tool that turns a valid `content.md` narration into a cinematic long-form YouTube storytelling video.

## Product modes

- **`hybrid_hook`** — AI video for the opening hook (default ~55 seconds), generated still imagery with restrained motion for the body, and optional AI-video motion spikes.
- **`full_video_ai`** — every final visual segment is video; still images may be used as references/keyframes but may not silently replace required final video.

## V1 provider choices

- TTS: **ElevenLabs** or **Typecast**.
- Planning LLM: **Gemini API**, baseline `gemini-3.5-flash`; `gemini-3.6-flash` is the first benchmark candidate.
- Image/video generation: **Google Flow** through an isolated browser-automation provider adapter.
- Final composition: local FFmpeg/FFprobe pipeline.

## User behavior authority

The V1 workflow is:

1. Import/create a project from `content.md`.
2. Select render mode, TTS provider/voice, and optional licensed/local BGM.
3. Generate narration and canonical alignment.
4. Generate story timeline, continuity bible, shot plan, and media plan.
5. **Human approval gate:** approve continuity + shot plan before any large Flow batch.
6. Generate a small reference set for recurring characters/locations/props.
7. **Human approval gate:** approve references and confirm the planned generation budget.
8. Generate image/video assets with per-request resume and bounded retries.
9. Review individual assets; approve/reject/regenerate/edit prompt/replace source where policy permits.
10. Resolve selected assets into an exact render plan and produce `final.mp4`.
11. Generate title/description and a Flow thumbnail; human-editable before use.

The CLI is the first canonical execution path. A local UI is added only after the hybrid pipeline is proven and must call the same application services rather than implement a second pipeline.

## Canonical project knowledge

- Product intent and requirements: `PROJECT_BRIEF.md`
- Accepted state: `PROJECT_STATUS.md`
- Architecture: `ARCHITECTURE.md`
- Engineering contract: `ENGINEERING.md`
- Roadmap: `ROADMAP.md`
- Frozen V1 design: `docs/specs/FROZEN_PRODUCT_DESIGN_V1.md`
- Domain model: `docs/specs/DOMAIN_MODEL_V1.md`
- Artifact contracts: `docs/specs/ARTIFACT_CONTRACTS_V1.md`
- Failure/recovery: `docs/specs/FAILURE_RECOVERY_V1.md`
- Acceptance: `docs/specs/QUALITY_ACCEPTANCE_V1.md`

## Build OS

Build OS v1.22 is adopted **outside this repository**. The product repository contains only its tracked adoption policy/authority records after bootstrap; `.buildos/` remains local control state and is excluded from Git by the OS.

## Production CLI

The CLI and application services are the canonical production path. Provider
execution remains explicit; local render and resume do not call Flow.

```text
python -m story_auto --runtime-root runtime new --project-id prj_example
python -m story_auto --runtime-root runtime run prj_example
python -m story_auto --runtime-root runtime resume prj_example
python -m story_auto --runtime-root runtime approve-plan prj_example
python -m story_auto --runtime-root runtime plan-visuals prj_example
python -m story_auto --runtime-root runtime approve-shot-plan prj_example
python -m story_auto --runtime-root runtime execute-generation prj_example --confirm-execute-generation
python -m story_auto --runtime-root runtime render prj_example
python -m story_auto --runtime-root runtime publishing-metadata prj_example
python -m story_auto --runtime-root runtime prepare-thumbnail prj_example
python -m story_auto --runtime-root runtime generate-thumbnail prj_example --confirm-execute-generation
python -m story_auto --runtime-root runtime finalize-thumbnail prj_example
```

`render` resolves only validated selected assets, publishes exact
`render_plan.json`, compiles every IMAGE/VIDEO/HOLD source to a silent normalized
scene MP4, generates SRT/ASS, mixes narration with optional local BGM, and
atomically publishes a validated `final.mp4` plus `final_manifest.json`.
Unchanged `resume`/`render` skips completed work; a missing scene rebuilds that
scene and the downstream final render without submitting to a provider.
