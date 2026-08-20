# Goal 22 — Replay genesis must not freeze replacement execution

## Verified product lesson

- Title: Replay genesis proof must not freeze mutable replacement execution state.
- Classification: `PRODUCT ARCHITECTURE / SPEC`.
- Verified symptom: a Goal 20 replay was valid at creation but became invalid
  after a legitimate pre-dispatch attempt because validation compared the whole
  replacement manifest entry to its original `PENDING / attempts=[]` shape.
- Root cause: immutable replay-creation provenance and mutable execution-state
  validation were conflated.
- Positive control: the former design failed closed before a provider
  submission, preventing unsafe re-entry.

## Control added

Goal 22 persists and validates a narrow immutable replay-genesis projection:
the old/replacement IDs, epoch and nonce, reason and acknowledgements, old
historical truth and attempts hash, request/prompt identity, dependencies,
references, queue position, and PREPARED/COMMITTED transaction lineage. Those
facts fail closed on mutation. Attempts, lifecycle status, and a future selected
asset are instead checked by the normal execution state machine.

Retry is permitted only for a persisted `NOT_DISPATCHED` attempt that positively
records `dispatch_confirmed=false`, no job/lineage/output evidence,
`PRE_DISPATCH_FAILURE`, `NOT_ATTEMPTED` attribution, and
`activation.input_dispatched=false`. A timeout, a missing job ID, a confirmed or
uncertain dispatch, uncertain/ambiguous attribution, or unresolved ownership is
a serial barrier.

## Workflow lesson

A runtime goal that discovers a source defect must be explicitly dispositioned
before a source-assurance goal takes authority. Goal 21 revision 1 was aborted
with `BLOCK_SOURCE_DEFECT_REPLAY_REENTRY_VALIDATOR`, preserving its runtime
evidence and making a later Goal 21 revision the only permitted continuation.

`unpersisted_os_findings=0`

`unpersisted_orchestration_findings=0`
