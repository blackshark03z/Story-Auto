# Decision 0001 — Reopen Full Video provider qualification

**Status:** Accepted
**Date:** 2026-09-10
**Scope:** `full_video_ai` only

## Context

Story Auto's accepted Full Image path uses Google Flow, while Full Video was
closed/deferred after provider/runtime uncertainty. The Owner has now explicitly
reopened Full Video to investigate Seedance-access providers, including providers
with free/trial access, before selecting a production path.

Existing Story Auto source already has provider-neutral generation requests and
manifests, VIDEO media contracts, full-video partitioning, provenance concepts,
and the common compositor. Reopening provider research does not justify replacing
those boundaries or introducing a general router in advance.

## Decision

1. Reopen provider qualification for `full_video_ai` only.
2. Keep `full_image` on its accepted Google Flow path during this Goal.
3. Treat Seedance as the current model family to evaluate; no provider is accepted
   until direct runtime evidence satisfies Goal 54 acceptance.
4. Begin with one provider-specific vertical slice using existing Story Auto
   contracts. Apply `REUSE -> WIRE -> FIX -> REPLACE_AND_DELETE -> ADD`.
5. Introduce a shared provider abstraction/router only if a second qualified
   provider demonstrates concrete contract variation that makes duplication or
   coupling materially worse.
6. Preserve provider-effect ambiguity and asset lineage. A timeout or uncertain
   result must not cause blind resubmission.
7. Free/trial availability is a qualification advantage, not proof of production
   reliability; terms, watermark, duration, resolution, quota/cost, acquisition,
   automation surface, and failure/recovery behavior remain separate evidence.

## Supersession

This decision supersedes only the prior closure of provider selection for Full
Video. It does not rewrite historical ADR-005 or historical runtime evidence, and
it does not reopen Hybrid or change the accepted Full Image provider baseline.

## Consequences

- Goal 54 owns the current Full Video provider research and first vertical slice.
- Candidate lists are discovery queues, not architecture commitments.
- `ARCHITECTURE.md` should change only after a provider path is actually qualified
  and integrated into canonical source.
