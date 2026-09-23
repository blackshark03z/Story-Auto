# Story Auto Architecture V1

Status: **CURRENT DURABLE ARCHITECTURE**. This document describes the architecture that exists now; Git/source and identified runtime evidence remain authoritative. Material rationale that must survive turnover belongs in Decision Records.

## Core principle

Experimental Flow VIDEO transport now exists in `providers/flow/rpc_transport.py`:
default-OFF, exact-project environment gate, existing authenticated Chrome session,
batchexecute contract with mandatory baseline and structural lineage checks,
durable per-attempt write journal, no automatic generation retry and read-only
reconciliation after uncertain submit. Supported scope is one PNG reference,
8-second 16:9 `abra_r2v_8s` output. Existing IMAGE routing and Dola are unchanged.
This is an installed candidate, not default production or owner-accepted stable.
See `docs/FLOW_RPC_INTEGRATION_STATUS.md` for exact evidence and outstanding gates.

Cookie-owned variant now has a named Windows-DPAPI session store and an explicit
Hybrid Opening reference-video action (`providers/flow/opening.py`). It reuses
the RPC transport with an owned headless browser instead of an external CDP
attachment. Per-slot account revision/project/reference/request binding and the
sealed RPC receipt guard canonical import; unresolved effects stay recovery-only.
This is a non-default, exact-project-gated candidate, not cookie qualification
for IMAGE or whole-product acceptance. See
`docs/FLOW_COOKIE_OPENING_DELIVERY_20260921.md` for evidence and remaining gates.

### Dola cookie adapter (2026-09-20 candidate)

Owner-directed `dola_cookie` is an experimental direct HTTP text-to-video
adapter for Hybrid Opening. Settings manages named cookie accounts in a
separate Windows DPAPI store. An explicit per-slot action binds account and
attempt before submit, commits the SSE conversation receipt immediately, and
resumes polling/acquisition on that same account. Downloaded video reuses the
canonical opening import, normalization, hash binding and composition path.
Five- or ten-second source clips are requested and trimmed to the opening slot;
reference images and observed upstream model identity remain unqualified.
This is distinct from the unimplemented `dola_official` placeholder. See
Decision 0011 for the Owner's change to the earlier official-only restriction.

An explicitly constructed browser UI transport also exists in
`providers/dola_cookie/browser_ui.py`. Its headed, bound persistent-profile
canary completed one live acquisition on 2026-09-23. It preserves profile
cookies, sends through the native UI once, confirms exact input readback before
accepting a conversation receipt, and reuses same-receipt recovery and canonical
import. This does not establish default product routing or unattended stability.
See [the browser UI runbook and Gemini comparison](docs/DOLA_BROWSER_UI_RUNBOOK_20260923.md)
for the successful source/runtime identity and archived reference guidance.

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

- Opening 15–20s: stable `OPENING_O*` video slots acquired manually or through an explicit provider action; body timing remains narration-owned.
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

Video generation is capability-first rather than provider-first. `Seedance` is a model family/capability requirement; BytePlus, Elyum and later providers are replaceable realizations behind a canonical registry/adapter boundary. The canonical request owns semantic intent, duration/aspect/resolution/reference requirements and effect identity; provider adapters own authentication, transport, provider job/preview state, retry/reconciliation and acquisition.

Cross-provider fallback is legal only before an external effect is confirmed or ambiguous. Once dispatch may have occurred, recovery must reconcile the same provider effect identity before any replacement/provider switch. Manual external generation remains an always-available Hybrid Opening acquisition path and converges to the same normalized/hash-bound slot contract.

Provider lifecycle is not forced into one universal state machine: BytePlus uses async task identity/polling, while Elyum preserves estimate/balance + locked preview + explicit Keep/Kill consequence semantics. Dola/session automation remains experimental until a stable provider contract is qualified.


Current production routing is explicit rather than inferred:

- `full_image` visual generation → `providers/flow/*` (`google_flow`), using the accepted dedicated browser/session boundary.
- `full_video_ai` visual generation uses a narrow capability-aware provider snapshot. `byteplus_seedance` remains the default/production-enabled path through `providers/byteplus_seedance/*` and BytePlus ModelArk's documented asynchronous task API. Goal 54 also records the qualified `elyum_seedance` I2V capability shape; its provider-free continuity lifecycle is implemented in `core/full_video_continuity.py`, its gated canonical-manifest adapter plus explicit preview-review / Keep / Kill consequence state in `providers/elyum_seedance/service.py`, and its product-safe canonical-state projection in `application/full_video_product.py`. Production Elyum routing remains disabled until bounded UAT is accepted.
- I2V continuity is not Flow entity-reference reuse. `output/full_video_continuity.json` owns run-scoped, generation-request-hash-scoped bindings. The first request requires an explicit canonical anchor; each later request may use only a deterministic local frame from the immediate prior accepted video. Binding revisions preserve exact source/reference hashes and become immutable once the downstream target enters a provider boundary.
- `providers/gemini_media/*` remains a non-routing experimental media adapter unless a later accepted decision changes production routing.
- Elyum is now a repeatability-qualified, engineering-gated Goal 54 integration candidate with continuity, canonical adapter, consequence state and product observability implemented. It is still excluded from ordinary production routing until bounded production UAT and an explicit routing-promotion decision are accepted.

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

Flow reference attachment is accepted only from a content-bound composer
postcondition. The adapter may read media bytes through the already-authorized
browser session from the narrow Flow/Google asset-host allowlist, but it does not
export or persist browser cookies. A selected-looking library tile, a closed
picker, or an Add-control exception is not success or failure by itself: the
adapter reconciles the composer, requires exactly one attached image whose
perceptual content matches the requested local reference, and fails closed before
Generate on zero, wrong, or multiple attachments. It never retries Add merely
because the activation reported an exception when the exact postcondition is
already true.

This attachment invariant is engineering-qualified for the current Flow surface.
The 2026-09-19/20 live evidence contains a bounded three-shot Flow VIDEO smoke
run with one exact reference and three valid eight-second MP4 downloads. A later
single canary passively observed one unique response-model identity triple whose
three UUIDs were present in the prompt-bound response chain, selected the exact
mapped tile, acquired a valid MP4, then recovered the same identity and exact
MP4 bytes after reload. The thumbnail bytes changed after reload, so thumbnail
URLs, hashes and gallery order are explicitly non-durable identity signals.

The observed response tuple is strong canary lineage evidence, not a documented
provider job contract. The canonical Flow VIDEO adapter now uses the bounded
passive decoder for attempt attribution while retaining its experimental
provider-contract classification. The module decodes only the response shape
already observed, requires
the tuple's middle UUID to equal the bound Flow project identity, assigns no
undocumented job/asset semantics to the outer UUIDs, and fails closed on token
collisions or resource limits. It never constructs/replays an RPC and retains no
raw response body, cookie or token. Two independent read-only reloads resolved
all six rendered video tiles identically through this module. An experimental
acquirer now accepts only one exact observed tuple, refuses missing or duplicate
matches and existing destinations, and selects the tile structurally rather
than by gallery order. A live reload recovery resolved 6/6 tiles, downloaded the
exact canary at 720p and reproduced the previously proven MP4 SHA-256 byte for
byte with zero Generate activations and zero RPC replays. The exact dedicated
Chrome process was then closed and reopened through Story Auto. Five identities
visible immediately before restart were a subset of the six visible after
restart; the canary remained unique and another 720p download reproduced the
same MP4 SHA-256 byte for byte, again without Generate or RPC replay.

Canonical attempt support persists the exact tuple only on an existing VIDEO
attempt whose project binding, request fingerprint, provider-boundary entry,
trusted activation epoch and attributable output all verify. The binding is hash-sealed,
idempotent for the same tuple and immutable against a conflicting tuple. The
canonical recovery entry point re-reads this binding from the generation
manifest before any provider observation, then re-reads it again immediately
before acquisition; operators do not supply tuple values to that path. This
ledger/acquirer composition is now also live-qualified by one isolated canonical
reference-to-video request. One trusted Generate produced a late result after the
480-second foreground wait, so the attempt first stopped `AMBIGUOUS`. Recovery
used the sealed pre-click response-set fingerprint, proved one unique bounded
delta, required exactly one member of that delta to map to a rendered video tile,
persisted its exact tuple before acquisition, and completed the same attempt with
zero further Generate activations. The selected 1280x720 H.264/AAC, 8.000-second
MP4 is SHA-bound in the manifest; reload recovery reproduced the same bytes.

Automatic binding on an in-time response and fail-closed late-output recovery are
therefore engineering-qualified for this isolated case. For VIDEO, the adapter
also persists a weaker recovery checkpoint immediately after one trusted Generate
activation and the provider/composer acceptance transition: it contains the
sealed pre-click response-identity set but does not confirm dispatch, own an
output, or authorize a retry. A restarted client may use it only to reconcile the
same attempt through an exact unique response delta. This path is live-qualified:
an isolated reference-video canary persisted a 16-identity checkpoint, the client
was interrupted during provider generation, and a later fresh client recovered
the unique 17th identity with one provider submission and no second Generate or
RPC replay. A subsequent binding-only reload reproduced the 8-second MP4 byte for
byte. Unattended multi-request operation and broader schema stability remain
unverified. This evidence does not change Full Video production routing:
Flow VIDEO remains a research/acceptance surface while the API-first BytePlus path
remains the production baseline.

If a VIDEO attempt has already persisted its exact response binding but crashes
before acquisition, reconciliation first verifies that saved binding and downloads
only the same tuple into the same canonical attempt; it never infers a new delta
or activates Generate. This closes the post-binding/pre-download local crash
window. A separate risk remains: passive same-project response deltas do not by
themselves exclude a concurrent manual Flow writer, and an empty prompt-editor
projection is weaker than an exact before/after prompt transition. Production
routing remains fenced pending a verified exclusive project epoch or equivalent
request-bound provider evidence.

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

## Final-output and recovery authority

The canonical production projection owns completion on Home, Workspace and
Review. A file named `final.mp4` alone is not completion: the renderer manifest
must bind the final bytes, current selected inputs, master tracks, render settings
and approved plan. The compact query cache tracks local input signatures; stale
Home actions refresh the project and cannot silently change the clicked intent.
Hybrid final manifests additionally bind effective master-track/presentation
settings. An older unbound output remains on disk but requires local rerendering
before it can represent current completion.

Opening API attempts retain their durable identity across interruption. A
BytePlus interrupted dispatch without a saved task ID is ambiguous, not permission
to create again. Elyum confirmed Keep is persisted before output acquisition;
acquisition recovery can fetch the same kept output without another Keep. Manual
replacement cannot hide an unresolved provider effect. Acquired source identity
and slot readiness are saved together. These are application recovery rules, not
a new CADS lifecycle.

## LLM abstraction

Planning resolves the provider from the saved project configuration. Gemini's
current configured HARD-first baseline is `gemini-3.8-flash`, with deterministic
fallback in `providers/llm/router.py`; Flash-Lite remains the BULK tier.

The optional `external_anthropic` adapter implements the Anthropic Messages
wire contract with a configured HTTPS gateway, model alias and authentication
mode. Project configuration retains the provider/model choice; changing defaults
affects new projects only. Credential pools remain inside the shared secret
boundary. The configured and gateway-reported model names are provenance, not
proof of upstream vendor identity. See Decision `0008-gemini-3-8-and-external-llm-gateway`.

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
