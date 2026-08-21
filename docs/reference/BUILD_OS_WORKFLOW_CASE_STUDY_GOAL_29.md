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
