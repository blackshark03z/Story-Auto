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
7. **Dola is experimental and official-contract-only until a stable developer API is qualified.** Story Auto must not implement Dola by reverse-engineering private/internal endpoints or importing browser/app cookies into an unofficial API path. Dola may later implement the same provider contract only through an official supported API contract; until then, users may still use Dola through the existing manual external-generation path.
8. Provider credentials use the existing Story Auto credential boundary; secrets never belong in project JSON, logs, diagnostics or committed source.

## Initial provider tiers

- Tier A: `byteplus_seedance` — direct documented async API, production baseline.
- Tier A: `elyum_seedance` — MCP/API provider with estimate/balance and Keep/Kill consequence lifecycle; promote incrementally from Goal 54 evidence.
- Tier B: `dola_official` — experimental placeholder for a future official Dola API contract; not production-routed. Unofficial cookie/internal-endpoint adapters are explicitly excluded.
- Tier C: `manual_external` — always-available acquisition fallback.

## Behavioral/System Flow invariant

`VideoGenerationIntent -> Provider Router -> Provider Adapter -> Canonical GeneratedAsset -> normalize/hash-bind -> exact slot/request`.

Provider-specific state may be richer internally, but downstream consumers receive canonical local asset provenance. A provider switch may never silently reuse an ambiguous effect identity from another provider attempt.

## Revisit triggers

Revisit routing policy when measured provider success/cost/latency/quality evidence is sufficient to support a smart router; when Dola exposes and documents a stable official API contract that can be qualified without reverse engineering; or when a provider changes billing/retry semantics materially.
