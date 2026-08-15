# Story Auto

Current stable release: **Story Auto v1.0.0 Stable**. See
[`docs/releases/v1.0.0.md`](docs/releases/v1.0.0.md) and the machine-readable
[`docs/releases/v1.0.0.json`](docs/releases/v1.0.0.json) regression manifest.

The current accepted post-release development state includes Goal 10’s
creator-first UI and Goal 11’s Flow IMAGE mark postprocessing. This is not a
new release version: `v1.0.0` remains the stable release baseline. Next use is
a real production trial through the normal UI; observed defects should become
narrow corrective work with regression coverage.

Story Auto is a local, artifact-first production tool that turns a valid `content.md` narration into a cinematic long-form YouTube storytelling video.

## Product modes

- **`hybrid_hook`** — AI video for the opening hook (default ~55 seconds), generated still imagery with restrained motion for the body, and optional AI-video motion spikes.
- **`full_video_ai`** — every final visual segment is video; still images may be used as references/keyframes but may not silently replace required final video.

## V1 provider choices

- TTS: **ElevenLabs**, **Typecast**, or explicit local **Kokoro Local**.
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

The CLI remains a canonical execution path. The local operator UI uses the same application services rather than implementing a second pipeline.

### Creator workspace

The local UI is organized around the creator journey rather than pipeline
internals:

1. **Home** lists projects by story title, human status, progress, and one next
   action. Work needing attention is separated from recent work.
2. **New video** guides Content, Style & Voice, and Review & Create in a
   recoverable dialog. The default free narrator is Kokoro Local's **George**.
3. **Project** shows the current production stage, useful progress, saved-work
   reassurance, and one primary Start or Resume action.
4. **Review** presents quality checks, flagged scenes, publishing copy, and the
   final video without exposing manifests or request IDs by default.
5. **Settings** groups defaults, provider health, and storage by user intent;
   raw paths, models, IDs, and manifest detail stay under Advanced or
   Diagnostics.

Errors preserve entered work and provide a specific next action. The interface
uses native labeled controls, a keyboard-focus ring, live status regions, and
responsive layouts for compact through large desktop windows. Canonical
artifacts and provider execution still flow exclusively through
`OperatorService` and the accepted core services.

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
python -m story_auto --runtime-root runtime execute-generation prj_example --confirm-execute-generation --all-ready --max-requests 20
python -m story_auto --runtime-root runtime render prj_example
python -m story_auto --runtime-root runtime publishing-metadata prj_example
python -m story_auto --runtime-root runtime prepare-thumbnail prj_example
python -m story_auto --runtime-root runtime generate-thumbnail prj_example --confirm-execute-generation
python -m story_auto --runtime-root runtime finalize-thumbnail prj_example
python -m story_auto --runtime-root runtime ui --host 127.0.0.1 --port 8765
```

The loopback-only operator UI opens at `http://127.0.0.1:8765`. It exposes the
same project, review, generation, render, and publishing services used by the
CLI; it does not write a parallel pipeline or require direct provider-page use.

`render` resolves only validated selected assets, publishes exact
`render_plan.json`, compiles every IMAGE/VIDEO/HOLD source to a silent normalized
scene MP4, generates SRT/ASS, mixes narration with optional local BGM, and
atomically publishes a validated `final.mp4` plus `final_manifest.json`.

`kokoro_local` is an explicit per-project provider choice. It invokes the
installed direct-Python Kokoro runtime through the common TTS contract, requires
no cloud credential, publishes 24 kHz mono WAV plus model-derived token timing,
and never silently replaces an existing ElevenLabs or Typecast selection.
Unchanged `resume`/`render` skips completed work; a missing scene rebuilds that
scene and the downstream final render without submitting to a provider.

Production image and video assets pause in `QC_PENDING` until the complete
naturalness rubric passes. For Flow IMAGE, the raw provider bytes are retained
as immutable evidence and a deterministic locally cleaned, lineage-validated
derivative becomes `selected_asset`; a remaining visible provider mark fails
QC. Flow VIDEO remains unchanged: its visible provider mark is the accepted V1
limitation.
Long `full_video_ai` shots are partitioned into stable provider-duration request
parts and every part must resolve to video before rendering. `NATURAL_SOFT` is an
optional restrained finishing profile with no blur or artificial sharpening.
