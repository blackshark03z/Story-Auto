# Decision 0002 — Full Video uses an API-first first-party provider path

**Status:** Accepted
**Date:** 2026-09-12
**Scope:** `full_video_ai`

## Context

Goal 54 initially surveyed multiple Seedance-access providers, including free web
surfaces. The Owner then made connection stability explicit: Story Auto must not
repeat the browser/session/UI drift and ambiguous connection failures experienced
with Flow for the new Full Video path.

## Decision

1. A Full Video production provider must expose a documented programmatic API,
   durable task/job identity, queryable terminal/non-terminal states,
   deterministic result acquisition, and safe reconciliation semantics.
2. Browser/session/CDP/UI automation is not an accepted Full Video production
   transport. Dola/Dreamina web routes may remain discovery/demo surfaces only.
3. Use first-party BytePlus ModelArk as the first implementation path for
   Seedance 2.5 model `dreamina-seedance-2-5-260628`.
4. Keep the adapter narrow. Do not introduce a generic provider router until a
   second qualified API provider creates concrete repeated variation.
5. A POST with uncertain outcome is an ambiguity boundary and must never be
   retried automatically. Once a task ID is known, resume by polling that exact
   task. Terminal provider failure requires an explicit replacement decision.
6. Preserve Google Flow only for the already accepted Full Image path; Full Video
   must not depend on Flow connection, browser profile, or Flow-generated
   reference images in this initial path.
7. Full Video quality review remains manual until an automated video QC oracle is
   separately accepted.

## Consequences

- Story Auto gains a direct BytePlus Seedance adapter and provider-specific
  readiness without a cross-provider routing layer.
- Stability and recoverability outrank free quota when selecting the production
  path.
- Live acceptance remains blocked until a ModelArk API key is configured and a
  bounded Stage B generation is evidenced. Engineering tests cannot substitute
  for that runtime proof.
- Third-party provider research is deferred, not rejected forever; reopen it only
  if the first-party path is materially blocked or a concrete second-provider
  requirement emerges.
