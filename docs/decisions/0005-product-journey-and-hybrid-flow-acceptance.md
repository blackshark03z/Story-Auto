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

### Owner priority update — 2026-09-18

The Owner explicitly deferred further visual/aesthetic quality optimization. Visual quality is backlog work and is **not a blocker** for the current Story Auto delivery goal.

Current acceptance priority is:

1. **Correct format contract** — each mode produces the expected canonical artifacts/media structure and preserves master narration/subtitle/waveform ownership.
2. **Correct, recoverable pipeline** — Run/Continue advances the intended stages without duplicate provider effects, stale-state leakage, hidden redispatch, or requiring the Owner to reconstruct backend state manually.
3. **Smooth CUJ** — the user can tell what just happened, what is running/complete/blocked, what action is next, and can reach the canonical final output or resume after interruption without redoing accepted work.
4. **Repeat-use readiness** — a completed run can safely lead to another run without stale context or artifacts being treated as current.

This deferment applies to aesthetic optimization such as motion naturalness, acting/expression quality, stock relevance polish, transition taste, pacing polish, and subtitle/waveform styling. It does **not** waive technical integrity, provenance, deterministic recovery, duration/media validity, security, or fail-closed behavior.

Canonical current status therefore remains:

`PRODUCT_FLOW_ACCEPTED / QUALITY_DEFERRED`

with active work focused on `FORMAT + PIPELINE + CUJ SMOOTHNESS` rather than Hybrid Quality V2 optimization.

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
