# Story Auto Architecture V1

Status: **CURRENT DURABLE ARCHITECTURE**. This document describes the architecture that exists now; Git/source and identified runtime evidence remain authoritative. Material rationale that must survive turnover belongs in Decision Records.

## Core principle

One modular production pipeline with mode-specific media policy and provider boundaries. Never build a separate Full Image, Full Video, or legacy-mode pipeline.

## Architecture drivers

- **Recoverability and external-effect identity:** a provider timeout, restart, or reconnect must not cause blind duplicate paid generation.
- **Provenance and timing integrity:** canonical alignment owns story time; every selected visual is bound to request/attempt/provider/model and local hash evidence.
- **Provider isolation:** planning/rendering remain provider-independent; browser/session details and API credentials stay inside adapters.
- **Operational stability:** Full Video production must prefer documented API task identity/polling over fragile browser/session automation.
- **Cost observability:** generation cost/quota is an external consequence and must be estimable/bounded before scaled execution.
- **Low-IT product journey:** the supported product path must remain understandable and recoverable without requiring provider implementation knowledge.
- **Acceptance-surface provenance:** any preview/UI/downloaded artifact used as Product or Owner acceptance evidence must be traceably bound to the candidate source/runtime, material configuration/data authority, provider request/job/result identity and local artifact lineage that can affect the claimed behavior; materially ambiguous or stale surface evidence is `UNVERIFIED`.

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
provider boundary
  ├─ Full Image → Google Flow browser adapter
  └─ Full Video → BytePlus ModelArk async API adapter
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

### ambient_story

Ambient Story reuses the durable story timeline, shot plan, media plan,
generation requests, manifest, and render plan. Its shot-plan policy first
identifies narrative-state candidates, then merges adjacent candidates only
when one truthful visual anchor remains valid. A shot is therefore a long-lived
**visual chapter**, but preferred asset count never authorizes merging action,
accusation, retirement/death, or other incompatible states. Duration alone
never forces a split.

The data-driven budgets are `quiet_verdict` preferred 2–5/hard maximum 8 and
`hidden_mastery` preferred 4–7/hard maximum 10. Overflow above the preferred
maximum requires a machine-readable semantic-incompatibility reason; overflow
above the hard maximum fails planning. A premise-level `SUPPORTIVE` anchor may
span compatible location changes when it does not assert misleading literal
detail.

The shot plan keeps `narrative_summary` separate from a bounded visual brief
(`visual_anchor`, dominant subject/environment/state, motif, continuity, and
optional context). Only the brief reaches Flow prompt compilation. The canonical
Flow IMAGE hard limit is 1,200 characters and Ambient compilation targets 1,100
with whole-field, priority-aware optional compaction. Required identity,
continuity, style, safe-area, and safety instructions are never raw-truncated;
irreducible overflow fails before a provider call.

Every Ambient media item is `IMAGE / REQUIRED`; overrides cannot request video
and temporal video QC is `NOT_APPLICABLE`. Style prompt directives participate
in visual-generation identity. Deterministic motion, fine-grain presentation,
subtitle preset, and transition settings remain local render inputs, so
local-only presentation changes do not invalidate Flow requests.

## Provider boundaries

Current production routing is explicit rather than inferred:

- `full_image` visual generation → `providers/flow/*` (`google_flow`), using the accepted dedicated browser/session boundary.
- `full_video_ai` visual generation uses a narrow capability-aware provider snapshot. `byteplus_seedance` remains the default/production-enabled path through `providers/byteplus_seedance/*` and BytePlus ModelArk's documented asynchronous task API. Goal 54 also records the qualified `elyum_seedance` I2V capability shape, but production dispatch remains disabled until its continuity lifecycle and production adapter are accepted.
- `providers/gemini_media/*` remains a non-routing experimental media adapter unless a later accepted decision changes production routing.
- Elyum is currently a bounded Goal 54 research candidate/revisit trigger only. Until runtime qualification and an accepted routing decision exist, it is not part of production architecture.

```text
core/application request
  ↓
provider-specific adapter boundary
  ├─ providers/flow/*                 Full Image
  ├─ providers/byteplus_seedance/*    Full Video
  ├─ providers/gemini_media/*         experimental/non-routing
  ├─ providers/tts/*
  └─ providers/llm/gemini
```

Core planning/rendering does not know Flow DOM selectors, browser profile paths,
BytePlus/Elyum credentials, provider result URLs, login state, provider button
labels, or provider-specific retry mechanics.

### BytePlus ModelArk Full Video responsibilities

- server-side API-key authentication kept outside committed source;
- Seedance async task creation through one documented POST boundary;
- immediate persistence of returned provider task identity before polling;
- polling/resume by the exact known task ID without another POST;
- fail-closed `AMBIGUOUS` state when POST outcome is uncertain;
- no automatic replacement task after ambiguous dispatch or terminal provider failure;
- deterministic HTTPS result acquisition, FFprobe validation, local hashing, and manifest provenance;
- Full Video results enter `QC_PENDING` and remain subject to manual video review until a stronger accepted oracle exists.

The current implementation model is `dreamina-seedance-2-5-260628`. BytePlus is
the stable first-party Full Video baseline/fallback while Goal 54 evaluates
whether a cheaper API-first route can satisfy the same recovery/provenance
invariants.

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

Flow Generate activation and provider dispatch acknowledgement are separate
contracts. The adapter resolves the unique enabled Generate control immediately
before one trusted CDP pointer sequence; it does not follow an acknowledgement
delay with keyboard, JavaScript, or OS-mouse activation. Prompt readback,
reference attachment completion, and an enabled control establish composer
readiness, but neither a click nor a generic composer/DOM transition counts as
a provider submission. Dispatch is confirmed only by attributable provider
evidence, currently a new request-bound output (or a provider job identifier or
job state if Flow exposes one). After input has occurred without that evidence,
the attempt is dispatch-uncertain and must reconcile before any new activation.

## TTS and alignment abstraction

```text
ElevenLabs → audio → forced alignment ───────┐
Typecast → audio + timestamps → normalize ──┼→ canonical alignment.json
Kokoro Local → WAV + model token timing ────┘
```

No silent cross-provider fallback. Downstream planning does not depend on which TTS provider produced the canonical alignment.

The Kokoro adapter owns discovery of its configured local installation, cached
model/voice identity, CPU worker invocation, resumable chunk artifacts, audio
validation, and sanitized failure classification. Core audio stages see only
the existing `TTSRequest`/`TTSResult` and canonical alignment boundaries.

## LLM abstraction

Gemini is the only planning LLM provider in V1. Model ID is project/provider configuration.

Baseline: `gemini-3.5-flash`.
Benchmark candidate: `gemini-3.6-flash`.

Each planning stage validates structured output and writes a versioned artifact. Invalid JSON/schema is a stage failure, not silently accepted prose.

## Acceptance-surface provenance

Story Auto frequently evaluates behavior through observed surfaces that can drift
from source or provider state: loopback UI pages, Google Flow browser surfaces,
Elyum/BytePlus provider previews, downloaded media, locally postprocessed assets,
and final renders. Evidence from such a surface is admissible only when the
material factors affecting the claimed behavior can be reconstructed and tied to
the intended candidate.

For provider-backed visual evidence, the minimal provenance envelope is normally:

- candidate Product HEAD/source state that produced the request/adapter behavior;
- render/research mode and material generation configuration;
- request or experiment identity plus provider/model;
- provider task/job/result identity when available;
- reference/input asset hash and lineage when material;
- acquired local artifact path + cryptographic hash + relevant technical metadata;
- applicable configuration/data authority (for example account/balance snapshot,
  manifest/ledger entry, selected-asset binding or review state);
- observed surface used for the claim, including whether it is a locked preview,
  kept original, local derivative or final product surface.

A provider preview can prove the identified preview candidate, but it does not by
itself prove a later kept/original asset, integrated render or canonical product
state when those materially differ. Likewise, Owner review of a local file is
valid only when that file's lineage to the intended provider result/candidate is
established. Self-reported version labels or UI text are supporting evidence, not
sole identity proof.

This is an acceptance invariant, not a deployment/promotion lifecycle. Record only
material provenance needed to reconstruct the claim.

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

The Flow queue is serial at the manifest boundary. Any generating, dispatch-
uncertain, attribution-uncertain, or attribution-ambiguous attempt is a global
barrier for that project queue across batch, retry, resume, CLI, and UI entry
paths. Resume reconciles the earliest unresolved attempt before any new
activation; an unresolved result leaves the queue halted.

Flow output identity is request-epoch provenance, not gallery order. After
reference attachment and immediately before activation, the adapter requires a
quiescent, consecutively stable provider surface and records its tile/asset
identity fingerprint. After one activation, attribution considers only the
provider delta from that baseline. One stable tile-to-asset lineage may be
bound; multiple unseen candidates without a unique placeholder/job lineage are
`OUTPUT_ATTRIBUTION_AMBIGUOUS`. Newest-card and timestamp-proximity fallbacks
are not attribution evidence. Dispatch confirmation and asset attribution are
separate states, and provider bytes cannot enter postprocessing or
`selected_asset` until attribution is confirmed.

## Human review

Review decisions live in a durable `review_state.json`, separate from plan artifacts and provider manifest. This prevents a regenerate/edit cycle from erasing the distinction between planned output, generated candidates, and operator choice.

## Composition boundary

Every selected visual source compiles to a normalized silent MP4 clip before the common final compositor. The final compositor therefore remains media-provider agnostic.

Ambient Story keeps this exact boundary: a selected, lineage-validated clean
Flow image derivative is compiled with a bounded deterministic primitive
(`STATIC`, subtle push/pull/pan, or micro drift) and optional seeded fine grain,
then enters the common compositor like every other silent normalized clip.

The implemented boundary lives under `core/render`, with separate render-plan,
FFmpeg/FFprobe, compiler, compositor, and checkpoint-aware service modules.
`core/subtitles` consumes canonical alignment directly; `core/publishing` owns
Gemini metadata and Flow thumbnail provenance. Publishing requests share the
generation ledger but are excluded from render fingerprints, so publishing
changes cannot invalidate video stages.

The production provider boundary is split by active render mode: Full Image
resolves to `GOOGLE_FLOW_WEB`; Full Video resolves to `byteplus_seedance`.
Upstream narration, continuity, shot/media planning, generation requests, and
rendering remain provider-independent.

For production Full Image, Flow-bound prompt policy carries a soft bottom-right
provider-mark safe area, and subtitle styles reserve extra right clearance. The
Flow adapter preserves provider-original bytes and creates a separately hashed
local derivative with the visible sparkle mark removed before `selected_asset`
is bound. The generation manifest records raw-to-derivative lineage, and local
cleanup failure is retried from raw bytes without another provider submit. The
supported versioned image profiles are `1280x720 v1` and `1376x768 v1`; unknown
geometry fails closed locally. This is a Flow IMAGE boundary, not a universal
watermark-removal system.

Flow VIDEO is historical/non-production for the reopened Full Video path. The
active Full Video adapter acquires provider-owned API output into Story
Auto-owned local storage, validates/hash-binds it, and the renderer consumes only
the selected local path and hash.

### External provider trust and revisit triggers

- Provider credentials are secrets stored outside committed source and must not
  appear in logs, evidence docs, or UI payloads.
- A provider marketing claim is discovery evidence only; production qualification
  requires identified runtime/account evidence.
- Browser/session automation is not an accepted Full Video production transport.
- Elyum may replace or complement BytePlus only after read-only account/model/cost
  preflight plus a bounded runtime probe prove task identity, idempotent create,
  deterministic result acquisition, and Story Auto provenance/recovery invariants.
- A second provider does not justify a generic router by itself; introduce shared
  abstraction only after concrete repeated variation demonstrates the need.

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
    flow/                  Full Image browser provider
    byteplus_seedance/     Full Video async API provider
    gemini_media/          experimental/non-routing media adapter
  cli/
  ui/                   loopback HTTP operator dashboard
```

Exact filenames are implementation choices. These ownership boundaries are not.
