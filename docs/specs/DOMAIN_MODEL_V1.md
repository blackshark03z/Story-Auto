# Domain Model V1

## Project

Stable production identity plus user configuration. Owns render mode, provider choices/settings references, render/audio defaults, and cost guardrails. It does not contain mutable pipeline state or secrets.

## Narration + Alignment

Narration is the source text. Canonical Alignment maps narration spans to master audio time and owns the final story clock.

## StoryScene

A semantic section of narration with start/end time, story role, and beat summary. StoryScene does not know providers.

## ContinuityEntity

A reusable visual identity/state record. Kinds include Character, Location, and Prop. Entities own wardrobe/condition/time-state variants and approved reference asset links.

## Shot

An editorial visual unit mapped to a StoryScene and target time interval. It expresses subject/action, camera intent, continuity state, and adjacency/handoff requirements. A Shot is not necessarily one provider call.

## MediaDecision

Desired production treatment for a Shot: `IMAGE | VIDEO | HOLD`, `REQUIRED | PREFERRED`, fallback policy, target duration, reference strategy, and still-motion intent. Render mode constrains valid decisions.

## ReviewDecision

Human approval bound to artifact/asset hashes. Plan approval, reference approval, asset approval/rejection, and batch confirmation are durable decisions separate from plans and provider state.

## GenerationRequest

Provider-ready request compiled from approved planning state. Purposes: `REFERENCE`, `SHOT`, `THUMBNAIL`. One Shot may emit multiple requests when provider capability requires splitting/extension.

## GenerationAttempt

One immutable provider attempt for a GenerationRequest, with explicit status, provider reference/diagnostic pointer, and optional resulting Asset. Automatic attempts are bounded.

## Asset

Validated local media with stable ID, project-relative path, SHA-256, media metadata, generation provenance, and review state. Old attempts are retained.

## RenderSegment

Exact final timeline interval backed by an approved selected source. Owns trim/fit/still-motion/transition and fallback disclosure. All source kinds compile to normalized silent MP4 before final composition.

## AudioPlan

Master narration plus optional operator-supplied/local licensed BGM. Generated Flow video audio is muted in V1.

## FinalManifest

Provenance binding for the produced final MP4: render plan, selected assets, audio/subtitle inputs, renderer settings, dimensions/duration/streams, and file hash.

## PublishingPackage

Human-editable title/description plus Flow thumbnail request/selection. It is not a YouTube publishing/upload action.

## Key relations

```text
Project
 ├─ Narration → Alignment → StoryScene*
 ├─ ContinuityEntity*
 ├─ Shot* → MediaDecision
 ├─ ReviewDecision*
 ├─ GenerationRequest* → GenerationAttempt* → Asset?
 ├─ RenderSegment* → selected Asset
 ├─ AudioPlan
 ├─ FinalManifest
 └─ PublishingPackage
```

## Identity rule

Identity is stable and opaque; mutable display names/paths are not identity. Durable artifacts use project-relative paths and hashes.
