# Decision 0005 — Product Journey vs Execution Pipeline and Hybrid flow acceptance

Date: 2026-09-16
Status: ACCEPTED

## Decision

Story Auto distinguishes two independent views of production:

- **Product Journey / CUJ**: the user-visible path from creating a project through the next required action to a final video.
- **Execution Pipeline**: the internal technical stages and operations that perform the work.

A passing Execution Pipeline does not imply a passing Product Journey. Conversely, Product Flow Acceptance does not mean visual-quality optimization is complete.

For Hybrid Visual V1 the accepted outer Execution Pipeline remains the canonical Story Auto pipeline:

`SOURCE -> TIMING -> PLAN -> VISUALS -> QUALITY -> RENDER`

Hybrid is a mode-specific implementation inside PLAN/VISUALS/QUALITY/RENDER. It is not a second production pipeline.

## Product-flow acceptance policy

Hybrid Visual V1 is accepted when the user can:

1. create/select Hybrid Visual;
2. reach a prepared 15–20 second Opening Builder;
3. copy exact per-slot prompts and create clips externally or through a future API path;
4. import each clip back into its exact durable slot;
5. continue production without redoing completed work;
6. acquire body images automatically through the existing Flow image boundary;
7. use semantic Pexels stock when available or deterministic image fallback when stock is unavailable;
8. keep narration, subtitles, waveform and optional BGM continuous across visual-source changes;
9. receive canonical `output/final.mp4` and `output/final_manifest.json`;
10. rerun/recover without stale final output being reported as current.

## Quality policy

Hybrid V1 uses `TECHNICAL_ONLY_V1` at the QUALITY stage for Product Flow Acceptance. This checks technical integrity and exact input binding. It does **not** claim that motion, acting, stock relevance, transitions, image effects, subtitle styling, waveform styling or pacing are quality-accepted.

Canonical status after this decision:

`PRODUCT_FLOW_ACCEPTED / QUALITY_DEFERRED`

Quality work proceeds as a separate improvement track and must not reopen the accepted Product Journey unless a quality change actually breaks the journey contract.

## Activation boundary

New Hybrid projects created through the product UI write `settings.hybrid_visual.cuj_enabled=true`. Historical Hybrid projects without that explicit activation remain fail-closed as `FEATURE_NOT_AVAILABLE`; this prevents a new product policy from silently mutating old project semantics.

Full Image remains the default for new projects.

## Provider boundaries

- Opening manual/external generation is first-class and does not require a provider call inside Story Auto.
- Body IMAGE acquisition reuses the accepted Google Flow image path.
- Pexels stock is optional for flow completion; no-key, no-result or acquisition failure may fall back to a generated image for that stock slot.
- Visual source audio never owns the master audio track.

## Consequences

- UI/product tests must test Product Journey transitions, not infer them from backend unit tests.
- Pipeline tests must continue to verify internal safety, provenance, stale-state rejection and idempotence.
- Product-flow acceptance and quality acceptance must be reported separately in TASK/evidence/release notes.
