# Decision 0004 — Hybrid Visual mode and Opening Builder

Date: 2026-09-15
Status: ACCEPTED_FOR_DESIGN / IMPLEMENTATION_NOT_STARTED
Owner decision: approved direction from product discussion

## Context

Story Auto currently treats still-image and full-video generation as distinct production directions. The next product need is a low-cost, high-retention visual mode that keeps narration/audio as the canonical timeline while alternating several visual asset types.

The owner wants the first 15–20 seconds to support a stronger video opening, followed by a repeating mixture of still images with motion/effects and relevant stock-video inserts. Subtitle and waveform behavior must remain continuous across the whole output.

The opening must work even when the user does not want to spend API credits. Story Auto therefore needs to generate a deterministic opening plan and prompts that can be taken to any external video-generation tool, then accept the generated 5–10 second clips back into the exact planned slots without guessing.

## Decision

### 1. Add a distinct `Hybrid Visual` product mode

Do not overload or silently mutate `Full Image`.

Product modes remain conceptually separate:

- Full Image: still-image driven, simple and predictable.
- Full Video AI: video-generation driven across the visual timeline.
- Hybrid Visual: Opening Builder + still-image blocks + stock-video blocks, while narration/subtitles/waveform remain continuous master tracks.

The Hybrid Visual mode is a visual-composition strategy. It must not fork the narration, subtitle, waveform, or audio timing pipeline.

### 2. Narration/audio is the master timeline

The canonical production clock is the narration/audio timeline.

Visual assets are overlays/slots scheduled against that clock. Changing an image, stock clip, or opening clip must not rewrite narration timing, subtitle timestamps, or waveform timing unless the owner explicitly regenerates those upstream artifacts.

Embedded audio from imported/generated visual clips is ignored/stripped by default. Story Auto owns the final audio mix.

### 3. Opening Builder is a first-class sub-workflow

Default target opening duration: 15–20 seconds.

The opening is not assumed to be one monolithic file. The planner creates a small sequence of stable slots, normally 2–4 clips of approximately 5–10 seconds each, for example:

- `OPENING_O1`: 0–6 s
- `OPENING_O2`: 6–12 s
- `OPENING_O3`: 12–18 s

Exact durations may vary while the total remains inside the accepted 15–20 second opening envelope.

Each slot has durable identity and stores at least:

- slot ID;
- target start/end/duration;
- semantic purpose/beat;
- exact prompt snapshot + prompt hash;
- shared continuity/style context;
- asset source (`MANUAL_IMPORT`, `API_GENERATED`, later other supported sources);
- bound input asset hash;
- normalized output asset hash;
- QC/normalization result;
- replacement history.

The manifest/slot ID is the source of truth. Filename conventions are convenience only.

### 4. Manual external generation is a supported primary path

The tool must support this complete journey:

1. analyze the opening narration/hook;
2. create an Opening Storyboard and stable slot IDs;
3. create a shared continuity/style block;
4. create one exact prompt per opening slot;
5. allow `Copy prompt` per slot and `Copy all prompts` for the full opening pack;
6. user generates 5–10 second clips in any external service/tool;
7. user imports each clip back into its exact slot;
8. Story Auto validates, normalizes and binds it to that slot;
9. rerender uses the same slot mapping deterministically.

Import must never guess which slot a clip belongs to when the user imports through a slot-specific action. Bulk import may use filenames such as `opening_O1.mp4`, but filename matching is only a shortcut and must fail closed on ambiguity.

### 5. API generation and manual generation share one slot contract

`Create by API` and `Import video` are two acquisition methods for the same opening slot. They must produce the same normalized downstream artifact contract.

A project may mix methods, e.g. O1 manual, O2 API, O3 manual.

Provider/API failure must not block the whole Hybrid Visual mode when a manual path is available. The UI should expose the unresolved slot and allow import instead of silently substituting a different visual.

### 6. Imported/generated clip normalization

Before a slot becomes READY, Story Auto validates at minimum:

- readable media;
- duration;
- width/height and aspect ratio;
- frame rate;
- codec/container compatibility;
- exact slot association;
- local SHA-256 binding.

The compositor normalizes to the project output contract. Embedded clip audio is stripped/ignored by default.

Duration mismatch policy:

- clip longer than slot: trim/select a valid segment; never time-stretch by default;
- clip slightly shorter than slot: first allow bounded opening-timeline rebalance when the total can remain 15–20 s;
- only use tiny speed/hold/transition compensation within explicit tolerances;
- large mismatch fails the slot and asks for replacement rather than visibly stretching the clip.

Replacing O2 must not change O1/O3 bindings.

### 7. Opening prompts are a coordinated prompt pack

Opening prompts are not generated as unrelated prompts.

The planner first creates shared continuity/style constraints, then creates shot-specific beats. A typical three-shot pack is:

- O1: hook/establishing beat;
- O2: development/action beat;
- O3: payoff/reaction/bridge into the ordinary Hybrid Visual timeline.

Every exported prompt pack carries the slot ID and intended duration so the external result can be imported unambiguously.

### 8. Post-opening Hybrid Visual recipe

After the opening, V1 alternates still-image blocks and stock-video blocks until the narration ends.

Recommended default behavior:

- image block: roughly 14–24 seconds containing 2–5 images;
- individual image display: roughly 4–7 seconds;
- stock-video block: roughly 5–10 seconds;
- controlled jitter/variation prevents a visibly mechanical fixed cadence;
- no two stock blocks back-to-back by default;
- no asset reuse inside one video unless explicitly allowed.

Image motion is restrained/cinematic: slow zoom in/out, pan, push, crop drift, dissolve/crossfade. Avoid decorative effects that distract from story narration.

### 9. Stock video must be semantically relevant, not globally random

For each stock slot, Story Auto derives search terms from the narration/scene context for that time range, searches the configured stock provider, then selects deterministically from a bounded relevant candidate set.

Randomness is allowed only inside a relevance-qualified candidate set. The system must not insert unrelated stock just to create movement.

A deterministic run seed and stored provider asset ID make rerenders stable.

### 10. Hybrid Visual V1 does not insert AI video throughout the body

V1 allows AI/manual video in the Opening Builder and stock video in the body. It does not yet schedule arbitrary AI-video slots throughout the full narration.

Reason: mid-body AI video introduces provider credit/retry/continuity/review consequences across many slots. The generic slot contract should allow this later, but V1 should reach stable daily-use acceptance first.

### 11. Product UI

Hybrid Visual should keep the owner workflow compact:

- Opening: Off / Manual / API / mixed, target 15–20 s;
- Images: motion intensity / approximate image duration;
- Stock video: On/Off, provider, frequency/mix;
- Mix: image-heavy / balanced / stock-heavy;
- Opening Builder: slot cards with time range, prompt, source, asset status, Import/Create/Replace actions;
- Recipe preview: human-readable timeline summary before Run.

Advanced normalization/search/provider details stay behind an advanced surface.

### 12. V1 acceptance

Hybrid Visual V1 is not Product Accepted until a real user journey proves:

- one-click production after required manual opening slots are filled;
- opening total remains inside the configured 15–20 second envelope;
- every imported opening clip is bound to the intended slot with immutable hash provenance;
- no unexplained visual gaps or overlaps;
- replacing one opening slot does not mutate siblings;
- narration, subtitles and waveform remain continuous from t=0 to final duration;
- embedded visual-clip audio cannot override master audio;
- stock videos are semantically relevant and deterministic on rerender;
- stock-provider failure falls back to an image slot or an explicit recoverable state, not whole-project failure;
- final render passes existing media/QC contracts.

## Non-goals for V1

- AI video generation for every body slot;
- automatic semantic judging of externally generated opening clips beyond bounded media/continuity/QC checks;
- forcing a single AI-video provider;
- forcing one exact number or duration of opening clips;
- replacing the existing Full Image or Full Video AI modes.

## Implementation sequencing

1. Freeze Hybrid Visual slot/manifest contract.
2. Implement Opening Builder planning/export/import/normalization first.
3. Prove manual opening round-trip with no provider API dependency.
4. Add API acquisition as an alternate source for the same opening slots.
5. Add stock-provider abstraction + Pexels V1 implementation.
6. Add Hybrid Visual compositor recipe over the existing master audio/subtitle/waveform pipeline.
7. Product UAT and promotion/activation under CADS.

This feature track is independent of Goal 54 Elyum qualification; implementation must not be mixed into the current Goal 54 consequence state.
