# Story Auto Architecture V1

Status: **FROZEN PRODUCT ARCHITECTURE**. Implementation details may evolve only when they preserve the invariants below or an owner-approved ADR creates a new design revision.

## Core principle

One modular pipeline, two media policies. Never build a separate hybrid pipeline and full-video pipeline.

```text
content.md
  ↓
TTS → voice
  ↓
canonical alignment.json                 ← timing authority
  ↓
story_timeline.json                      ← story meaning + timing
  ↓
continuity_bible.json                     ← characters / locations / props / states
  ↓
shot_plan.json                            ← what the viewer should see
  ↓
media_plan.json                           ← IMAGE / VIDEO / HOLD + requirement policy
  ↓
review_state.json                         ← plan approval gate
  ↓
generation_requests.json                 ← provider-ready requests, references first
  ↓
Google Flow adapter
  ↓
generation_manifest.json + assets        ← attempts / hashes / status / provenance
  ↓
review_state.json                         ← asset/reference approvals
  ↓
render_plan.json                          ← exact selected sources and durations
  ↓
IMAGE → image compiler ─┐
VIDEO → video compiler ─┼→ normalized silent MP4 scene clips
HOLD  → hold compiler  ─┘
  ↓
common compositor
  ↓
audio_plan.json + subtitles
  ↓
final.mp4 + final_manifest.json
  ↓
publishing_package.json + thumbnail
```

## Timing ownership

Narration/alignment owns the master duration. Visual planning and generation conform to it; media generation may not redefine story time.

Final visual coverage must tile the narration interval without unexplained gaps. Transition math must preserve the final master duration within the renderer tolerance defined by acceptance tests.

## Planning boundaries

### Story timeline

Answers: **what story content is active, and when?** It contains no Flow selectors or provider runtime state.

### Continuity bible

Structured identity and state for recurring characters, locations, props, wardrobe, time-of-day, style, and reference assets. Continuity is data, not merely prose copied into prompts.

### Shot plan

Answers: **what should the viewer see?** One story scene may contain multiple shots. A shot is an editorial unit, not necessarily one provider call.

### Media plan

Answers: **how should each shot be produced?** It owns mode policy, media type, required/preferred semantics, fallback rules, reference strategy, and target duration.

### Generation requests

Provider-ready compiled instructions. One shot may map to multiple requests if provider capability/duration requires it. Reference-image and thumbnail requests use the same provenance system with different `purpose` values.

### Render plan

The exact source-of-truth for final composition: selected asset(s), trims, fit/crop, still motion, transition, and target duration. Desired media and actual rendered media remain distinguishable.

## Render-mode policy

### hybrid_hook

- Opening ~55s: `VIDEO / REQUIRED` by default.
- Body: `IMAGE / REQUIRED` by default.
- Motion spikes: `VIDEO / PREFERRED` or `VIDEO / REQUIRED` as explicitly planned.
- A preferred spike may fall back only when the media plan explicitly permits it and the fallback is recorded.

### full_video_ai

Every final shot resolves to `VIDEO / REQUIRED`. A still may never silently satisfy a required video shot.

Shots longer than the configured provider clip duration compile into ordered,
stable request parts. The render plan tiles those video parts over the original
shot interval with internal cuts; missing parts block rendering. Full-video
normalization never uses freeze-tail continuation.

## Provider boundaries

`story_auto.providers.gemini_media` is the official Gemini API media boundary.
It accepts provider-independent prompts and local continuity references, owns
model discovery, key rotation, Interactions image/Omni execution, Veo long-running
job polling, atomic local acquisition, and append-only attempt provenance. Veo
operation identity is committed before polling so restart never blindly submits
a second paid job. Signed result URLs and API keys never cross the adapter.

This adapter does not change production routing by itself. Flow and Gemini API
remain benchmark candidates until the owner completes the anonymous quality
review and explicitly accepts routing.

```text
core/application request
  ↓
provider interface
  ↓
providers/tts/{elevenlabs,typecast}
providers/llm/gemini
providers/flow/*
```

Core code does not know Flow DOM selectors, browser profile paths, login state, project URL details, provider button labels, or provider-specific error strings.

### Google Flow provider responsibilities

- dedicated Story Auto browser profile/session;
- capability discovery;
- fail-closed prompt/composer selection;
- request submit + readback/verification;
- bounded polling;
- result discovery;
- image extraction/video download;
- asset validation;
- explicit error classification;
- diagnostics.

It does **not** decide story beats, media policy, continuity, or final editorial timing.

## TTS and alignment abstraction

```text
ElevenLabs → audio → forced alignment ─┐
                                      ├→ canonical alignment.json
Typecast → audio + timestamps → normalize ┘
```

No silent cross-provider fallback. Downstream planning does not depend on which TTS provider produced the canonical alignment.

## LLM abstraction

Gemini is the only planning LLM provider in V1. Model ID is project/provider configuration.

Baseline: `gemini-3.5-flash`.
Benchmark candidate: `gemini-3.6-flash`.

Each planning stage validates structured output and writes a versioned artifact. Invalid JSON/schema is a stage failure, not silently accepted prose.

## Runtime isolation

Source and runtime are separate.

Conceptual home:

```text
STORY_AUTO_HOME/
  projects/
  browser/flow-profile/
  cache/
  temp/
  logs/
  evidence/
  locks/
```

No YouTube Auto runtime/project/browser profile may be reused. Tests use temporary roots.

## Generation state and concurrency

The generation manifest is the canonical provider/provenance ledger. Each request has immutable attempts. Successful requests are reused when request identity matches.

A global Flow-generation lock prevents two Story Auto production projects from driving the same browser/profile concurrently. Local planning/render work for other projects may continue when safe.

Explicit production-batch execution may process repeated request kinds. It keeps
the same request/attempt ledger and supports a per-invocation request boundary;
successful and QC-pending identities are never resubmitted on resume.

## Human review

Review decisions live in a durable `review_state.json`, separate from plan artifacts and provider manifest. This prevents a regenerate/edit cycle from erasing the distinction between planned output, generated candidates, and operator choice.

## Composition boundary

Every selected visual source compiles to a normalized silent MP4 clip before the common final compositor. The final compositor therefore remains media-provider agnostic.

The implemented boundary lives under `core/render`, with separate render-plan,
FFmpeg/FFprobe, compiler, compositor, and checkpoint-aware service modules.
`core/subtitles` consumes canonical alignment directly; `core/publishing` owns
Gemini metadata and Flow thumbnail provenance. Publishing requests share the
generation ledger but are excluded from render fingerprints, so publishing
changes cannot invalidate video stages.

For V1, the provider execution boundary resolves both image and video requests
to `GOOGLE_FLOW_WEB`; upstream narration, continuity, shot/media planning,
generation requests, and rendering remain provider-independent. Flow-bound
prompt policy carries a soft bottom-right provider-mark safe area, and subtitle
styles reserve extra right clearance. The visible Flow mark is retained as an
accepted known limitation; no processing stage removes or covers it.

## UI boundary

The CLI and loopback-only local UI invoke `application.OperatorService` and the
same core services/artifact contracts. HTTP handlers perform routing and input
decoding only; they do not write provider state or render files through a
second execution path. The UI never binds to a non-loopback address.

## Module map

Target modular monolith:

```text
story_auto/
  application/          orchestration/use cases
  core/
    content/
    audio/
    timeline/
    continuity/
    shots/
    media/
    review/
    generation/
    render/
    subtitles/
    publishing/
    checkpoint/
  providers/
    credentials/
    tts/
    llm/
    flow/
  cli/
  ui/                   loopback HTTP operator dashboard
```

Exact filenames are implementation choices. These ownership boundaries are not.
