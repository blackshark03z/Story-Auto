# Story Auto

Current stable release: **Story Auto v1.0.0 Stable**. See
[`docs/releases/v1.0.0.md`](docs/releases/v1.0.0.md) and the machine-readable
[`docs/releases/v1.0.0.json`](docs/releases/v1.0.0.json) regression manifest.

The current post-release implementation includes Goal 10’s creator-first UI,
Goal 11’s Flow IMAGE mark postprocessing, Goals 16–17’s Flow dispatch and
asset-attribution recovery, Goal 19’s legacy-only recovery transaction, and a
Goal 20 local R3 candidate for immutable poll evidence and explicit unresolved
replay. This is not a new release version: `v1.0.0` remains the stable release
baseline. Trial A is blocked at a fresh unresolved request; Goal 20 must receive
independent R3 approval before any runtime recovery, and Trial B has not started.

Story Auto is a local, artifact-first production tool that turns a valid `content.md` narration into a cinematic long-form YouTube storytelling video.

## Production modes on current main

The `v1.0.0` tag remains the stable release baseline; the statuses below describe the current post-release `main` product state.

- **Full Image (`full_image`)** — stable/default path: images only, deterministic local motion, and optional waveform presentation.
- **Hybrid Visual (`hybrid_hook`)** — **Product Flow Accepted / Quality Deferred**: 15–20s Opening Builder, automatic body images, semantic Pexels stock or image fallback, continuous narration/subtitles/waveform, and canonical final render. New UI-created projects carry an explicit CUJ activation flag; historical unflagged Hybrid projects remain fail-closed.
- **Full Video (`full_video_ai`)** — direct Seedance API path; its provider/quality qualification is tracked separately from Hybrid Visual.

Ambient Story remains preserved as historical development work and is not a
release-supported creation mode during this freeze.

## V1 provider choices

- TTS: **ElevenLabs**, **Typecast**, or explicit local **Kokoro Local**.
- Planning LLM: **Gemini API**, baseline `gemini-3.5-flash`; `gemini-3.6-flash` is the first benchmark candidate.
- Image/video generation: **Google Flow** through an isolated browser-automation provider adapter.
- Final composition: local FFmpeg/FFprobe pipeline.

## User behavior authority

The V1 workflow is:

1. Import/create a project from `content.md`.
2. Select Format, Ambient Style when applicable, TTS provider/voice, and optional licensed/local BGM.
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
2. **New video** guides Content, Format & Voice, and Review & Create in a
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

- Operating map: `AGENTS.md`
- Active intent: `TASK.md`
- Product intent and requirements: `PROJECT_BRIEF.md`
- Historical project-status snapshot: `PROJECT_STATUS.md`
- Architecture: `ARCHITECTURE.md`
- Engineering contract: `ENGINEERING.md`
- Roadmap: `ROADMAP.md`
- Frozen V1 design: `docs/specs/FROZEN_PRODUCT_DESIGN_V1.md`
- Domain model: `docs/specs/DOMAIN_MODEL_V1.md`
- Artifact contracts: `docs/specs/ARTIFACT_CONTRACTS_V1.md`
- Failure/recovery: `docs/specs/FAILURE_RECOVERY_V1.md`
- Acceptance: `docs/specs/QUALITY_ACCEPTANCE_V1.md`

## Build OS

Start with `AGENTS.md` for the operating map and `TASK.md` for active intent;
`ARCHITECTURE.md` carries durable product architecture. Legacy Build OS adoption
material is historical provenance, not current execution authority. When it is
available and explicitly requested, Simplified Build OS guards consequential
boundaries rather than normal development.

## Production CLI

The CLI and application services are the canonical production path. Provider
execution remains explicit; local render and resume do not call Flow.

Install Story Auto's supported Python dependencies before using the CLI:

```text
python -m pip install -r requirements.txt
```

The Flow Generate transport uses Playwright only to attach over CDP to Story
Auto's existing dedicated Chrome session. It does not launch a Playwright
browser or require `playwright install` browser binaries.

```text
python -m story_auto --runtime-root runtime new --project-id prj_example
python -m story_auto --runtime-root runtime new --project-id prj_ambient_example --render-mode ambient_story --ambient-style quiet_verdict
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
`Ready` means the configured runtime can load the exact local model snapshot and
selected voice. Projects may pin the canonical Hugging Face cache directory and
40-character snapshot revision with `model_cache` and `model_snapshot`; the
load-only readiness probe stays offline and is cached after success. Missing
runtime, model, voice, invalid configuration, and runtime-load failures remain
distinct, actionable preflight states before synthesis or downstream work.
Unchanged `resume`/`render` skips completed work; a missing scene rebuilds that
scene and the downstream final render without submitting to a provider.

`ambient_story` requires `settings.ambient_style` to be `quiet_verdict` or
`hidden_mastery`. Its visual planner groups ordered story-timeline scenes at
semantic state changes, targets 2–5 or 4–7 chapter images respectively, rejects
all video media overrides, and records deterministic motion/overlay parameters
in the normal media/render plans. It still resolves the exact Goal 11 clean
Flow derivative, compiles each image to a normalized silent MP4, and uses the
same compositor, subtitles, narration, and optional BGM as existing formats.

Production image and video assets pause in `QC_PENDING` until the complete
naturalness rubric passes. For Flow IMAGE, the raw provider bytes are retained
as immutable evidence and a deterministic locally cleaned, lineage-validated
derivative becomes `selected_asset`; a remaining visible provider mark fails
QC. Flow VIDEO remains unchanged: its visible provider mark is the accepted V1
limitation.

### Flow activation and resume safety

Flow dispatch confirmation and asset attribution are separate facts. Before one
activation, the adapter records a stable provider tile/asset baseline; afterward
it may attribute only the stable, request-specific delta. Stale or foreign
provider output is excluded. Multiple candidates without one trustworthy
tile/job lineage are ambiguous, and neither newest-card order nor timestamps
can choose an owner. Provider bytes cannot reach postprocessing or
`selected_asset` until attribution is confirmed.

Every provider-surface poll is retained in a bounded, sanitized, hash-chained
timeline. A transient job transition without a serialized stable provider
identity cannot confirm dispatch. If provider truth remains irreducible, the
only fresh-epoch path is a distinct manual recovery that acknowledges possible
prior and replacement cost, preserves the old unresolved attempt, and itself
makes zero provider calls.

The executor treats generating, dispatch-uncertain, attribution-uncertain, and
attribution-ambiguous attempts as a serial queue barrier across UI, CLI, batch,
retry, and resume. Resume first reconciles the earliest unresolved attempt; if
it cannot resolve the request safely, it makes no new Flow activation. For the
preserved Trial A project, use this path only—never a replacement project,
blind re-submit, or gallery-item guess.

Future `full_video_ai` work requires causal or otherwise uniquely proven
provider-result attribution; newest-card, first-card, last-card, and timestamp
heuristics are forbidden. `NATURAL_SOFT` is an optional restrained finishing
profile with no blur or artificial sharpening.
