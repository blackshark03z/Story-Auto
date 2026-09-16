# Decision 0006 — Capability-first video provider boundary

Date: 2026-09-16
Status: ACCEPTED

## Context

Hybrid Opening now supports manual import and BytePlus API generation, while Goal 54 has already qualified substantial Elyum Seedance behavior. Additional provider access such as Dola may be useful, but provider-specific control flow must not leak into the canonical Story Auto pipeline or create parallel product paths.

Current CADS guidance requires durable decisions to be phrased around capabilities/invariants rather than volatile provider/model products, and consequential external effects must make effect identity, ambiguity, idempotency, retry safety and authorization explicit.

## Decision

1. **Model and provider are separate identities.** `Seedance` is a model family/capability requirement; BytePlus, Elyum and later Dola are replaceable provider realizations.
2. **One canonical video-provider contract/registry** describes provider capability, transport class, lifecycle, consequence model, production status and experimental status. Planning/rendering remain provider-independent.
3. **Provider routing is explicit and deterministic.** Initial automatic policy means ordered readiness/fallback, not cheapest/best-quality inference.
4. **Cross-provider fallback is allowed only before confirmed or ambiguous dispatch.** `NOT_CONFIGURED`, capability mismatch, preflight failure and confirmed-not-dispatched may choose another provider. Ambiguous/confirmed dispatch must reconcile the same provider/effect identity first.
5. **Elyum keeps its own consequence lifecycle.** Preview creation/hold, Owner review, `Keep` spend and `Kill` release are not flattened into the BytePlus async-task lifecycle.
6. **Manual external generation remains universal fallback** for Hybrid Opening and converges into the same normalized slot contract.
7. **Dola is experimental/session-based until a stable official developer contract is qualified.** It may later implement the same provider contract, but cookie/session automation must stay isolated from core planning/rendering and cannot be a stable dependency yet.
8. Provider credentials use the existing Story Auto credential boundary; secrets never belong in project JSON, logs, diagnostics or committed source.

## Initial provider tiers

- Tier A: `byteplus_seedance` — direct documented async API, production baseline.
- Tier A: `elyum_seedance` — MCP/API provider with estimate/balance and Keep/Kill consequence lifecycle; promote incrementally from Goal 54 evidence.
- Tier B: `dola_session` — experimental session provider, not production-routed.
- Tier C: `manual_external` — always-available acquisition fallback.

## Behavioral/System Flow invariant

`VideoGenerationIntent -> Provider Router -> Provider Adapter -> Canonical GeneratedAsset -> normalize/hash-bind -> exact slot/request`.

Provider-specific state may be richer internally, but downstream consumers receive canonical local asset provenance. A provider switch may never silently reuse an ambiguous effect identity from another provider attempt.

## Revisit triggers

Revisit routing policy when measured provider success/cost/latency/quality evidence is sufficient to support a smart router; when Dola exposes a stable official API contract; or when a provider changes billing/retry semantics materially.
