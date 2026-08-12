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
