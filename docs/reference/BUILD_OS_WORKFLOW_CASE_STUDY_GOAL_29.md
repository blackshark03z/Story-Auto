# Goal 29 — Replacement lineage is transitive, not a direct-child state claim

## Product case study

- Title: Canonical replacement lineage must resolve immutable edges transitively.
- Classification: `PRODUCT ARCHITECTURE / SPEC / WORKFLOW`.
- Verified failure: a valid unresolved replay `A -> B` was later replaced for
  mandatory QC as `B -> C`.  The queue audit treated `B`'s absence from the
  live request list as an invalid `A -> B` edge, so it blocked before the
  intended current request `C` could be considered.
- Reusable rule: historical replacement records prove a single immutable edge;
  they do not assert that their direct child remains the current executable
  request.  Canonical selection must walk the proved edges until it reaches the
  one current request.

Goal 29 retains all historical attempt, dispatch, attribution, selected-asset,
and QC evidence.  The resolver verifies the committed transaction and immutable
identity of every edge, rejects duplicates, missing receipts, logical identity
changes, cycles, and a missing or ambiguous current descendant, and returns only
the final live request.  It never reopens or dispatches an ancestor.

The same rule covers legacy supersession, unresolved replay, and mandatory-QC
replacement: an earlier entry may be historical, but every edge remains
independently verifiable.  A current ambiguous descendant remains a queue
barrier; it does not make an earlier epoch runnable.

## Deferred Build OS and workflow findings

- Product continuation after a runtime-discovered source defect requires an
  explicit, auditable abort-and-rebootstrap handoff.
- The package workflow should make that handoff discoverable without implying
  that an aborted runtime operation has been retried or resumed.

Classification: `BUILD_OS / WORKFLOW / DISCOVERABILITY`.

No Build OS implementation was modified for these findings.

`unpersisted_os_findings=0`

`unpersisted_orchestration_findings=0`

## Revision 2 composition correction

- Title: Valid transitions require explicit composition proof.
- Classification: `PRODUCT ARCHITECTURE / SPEC / WORKFLOW`.
- Verified external-R3 gap: the initial transitive resolver could walk an
  `A -> B -> C` chain, but the replay validator accepted a missing child only
  when that child was QC-replaced, while the QC validator required its child to
  remain in the live request list. A valid `A -> B -> C -> D` chain therefore
  resurrected a historical barrier when `C` was replayed to `D`.
- Reusable rule: edge validity is independent from child liveness. Each edge
  verifies its own committed transaction/genesis and immutable manifest
  identity; only the resolver decides whether the final descendant is current.

Revision 2 supports composition across every existing canonical replacement
parent status without special-casing a particular child type. A child missing
from the live queue is accepted only when it is itself a canonical historical
parent, whose outgoing edge is then independently verified. Corrupt edges,
unsupported transitions, duplicate current children, cycles, and an ambiguous
current descendant still fail closed.

The offline regression preserves the historical chain rather than flattening
it: `A --replay--> B --QC replacement--> C --replay--> D`. It proves that only
`D` reaches the fake provider boundary; no production runtime artifact or
provider call is involved.

Deferred Build OS lesson: transition-composition and lineage-closure scenarios
should be required during future recovery-plan assurance. Broad synthesis
remains deferred until Story Auto ships.

## Revision 3 direct-edge correction

- Title: ancestry metadata is not direct transition proof.
- Classification: `PRODUCT ARCHITECTURE / SPEC / WORKFLOW`.
- Verified external-R3 gap: a QC child can later be replayed multiple times.
  Those descendants retain the QC ancestry fields copied from their immediate
  predecessor, which must not make them competing direct QC children of the
  original rejected request.
- Reusable rule: direct QC-child detection is based exclusively on a
  receipt-verified QC creation transaction whose immutable parent event and
  child genesis name that exact parent and child. Copied request fields are
  ancestry metadata only.

Revision 3 proves `A -> B -> C -> D -> E` without flattening the historical
edges: the one receipt-proven direct QC child of `B` is `C`; `D` and `E` are
replay descendants, even when they preserve `B`'s QC ancestry. Two separately
receipt-proven direct QC transactions for the same parent deny resolution.

Deferred Build OS lesson: assurance should distinguish ancestry metadata from
direct transition proof and compose transition checks across deeper canonical
lineage. No Build OS implementation is modified here.
