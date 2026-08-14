# Artifact Contracts V1

The JSON Schemas in `contracts/schemas/` are the machine-oriented companion to this semantic contract. Implementation models may use Pydantic/dataclasses/etc., but serialized artifacts must preserve these semantics.

## Common rules

- UTF-8 JSON.
- Explicit `schema_version`.
- Stable `project_id` independent of display/path slug.
- Project-relative media paths.
- Atomic writes.
- Direct input hashes in stage fingerprints.
- Secrets never serialized.
- Times are seconds from narration start unless otherwise stated.

## project.json

Owns user configuration, not mutable pipeline state.

Key domains:

- render mode;
- explicit TTS provider (`elevenlabs`, `typecast`, or `kokoro_local`) and
  provider-specific settings; Kokoro settings include its runtime, voice,
  language, speed, device, and chunking policy without cloud credentials;
- Gemini model configuration;
- Flow provider selection/config references;
- render dimensions/fps;
- hybrid hook target;
- audio/BGM configuration;
- cost/retry guardrails.

Changing a setting invalidates only stages that declare it as a direct fingerprint input.

## alignment.json

Canonical timing authority after TTS.

Contains:

- narration/audio hashes;
- master duration;
- ordered text segments and optionally word spans;
- normalized provider source metadata.

Downstream modules do not consume provider-native timestamp formats.

## story_timeline.json

Ordered story scenes. Each scene has stable-in-revision ID, start/end, narration span/text, story role/beat, and planning notes. It does not contain Flow request state.

## continuity_bible.json

Structured reusable entities and states:

- characters + wardrobe states + reference assets;
- locations + lighting/time states + layout anchors;
- props + state transitions;
- global style lock/negative constraints.

## shot_plan.json

Ordered editorial shots covering the narration timeline. One story scene may contain multiple shots.

A shot contains target timing, subject/action, camera intent, entity references, adjacency/handoff notes, and continuity state references.

## media_plan.json

Desired production policy per shot:

- `IMAGE | VIDEO | HOLD`;
- `REQUIRED | PREFERRED`;
- target duration;
- provider intent;
- reference strategy;
- fallback policy;
- still-motion intent when image-based.

Semantic validator enforces mode invariants (`full_video_ai` means every final shot desires VIDEO/REQUIRED).

## review_state.json

Durable human decisions, separate from planning/provider state:

- plan approval;
- reference approval;
- per-asset approval/rejection;
- batch confirmations;
- optional operator notes.

Review state references artifact/asset hashes so an approval cannot silently carry across materially changed content.

## generation_requests.json

Compiled provider-ready requests.

Purposes include:

- `REFERENCE`;
- `SHOT`;
- `THUMBNAIL`.

One shot may compile into multiple requests when provider capability requires splitting/extension. Requests contain prompt, reference asset IDs, requested media type/duration/aspect, provider, and optional provider hints.

## generation_manifest.json

Canonical provider ledger. For each request:

- request identity hash;
- attempts;
- explicit state;
- provider diagnostics/reference IDs where safe;
- selected asset;
- local path + SHA-256;
- failure class.

Attempts are append-only. A timeout does not imply safe re-submit until reconciliation decides whether the previous request actually completed.

## render_plan.json

Exact final source selection and editorial treatment:

- shot/segment ID;
- selected asset/path/hash;
- source kind;
- trim/fit/crop;
- image motion;
- transition;
- exact target timeline interval.

Required unresolved media blocks render. Fallback use is explicit and inspectable.

## audio_plan.json

- master narration path/hash;
- optional local BGM path/hash;
- BGM loop/fade/ducking policy;
- generated video source audio policy = `MUTE` in V1.

## publishing_package.json

- title candidates;
- selected/editable title;
- description;
- optional tags/hashtags if implemented;
- thumbnail request/selected asset/hash;
- approval status.

## final_manifest.json

Binds the actual final output to:

- exact render-plan hash;
- alignment/audio-plan/subtitle hashes;
- selected asset hashes;
- renderer settings/version;
- final file SHA-256, duration, dimensions, and streams;
- publishing-package pointer/hash when available.

This is the final provenance record for a produced artifact.

## ID conventions

IDs are opaque/stable; display labels are mutable.

Recommended readable forms:

```text
project: prj_<opaque>
scene:   scn_0001
shot:    sh_0001
entity:  char_*, loc_*, prop_*
request: req_<opaque>
asset:   ast_<opaque>
```

Do not encode mutable filenames or absolute paths into identity.
