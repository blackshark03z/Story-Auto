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

## External R3 corrective findings

### FAILED_RETRYABLE is state, not provider-resubmission authority

- Classification: `PRODUCT ARCHITECTURE / SPEC`.
- Verified failure shape: a generic retryable status could bypass the positive
  no-dispatch predicate and enter another provider generation attempt.
- Control added: every request with an existing attempt now reaches Generate
  only when its latest attempt satisfies the canonical positive no-dispatch
  predicate. `FAILED_RETRYABLE`, a missing job ID, a false dispatch flag, a
  timeout, and an error label are diagnostic state, not authority.
- Local-only recovery remains separate: it may work on already-owned bytes but
  cannot use this path to create another provider generation.

### Durable output ownership must precede fallible asset acquisition

- Classification: `PRODUCT ARCHITECTURE / SPEC`.
- Verified failure shape: a stable exact provider candidate could be fetched
  before its raw poll and authoritative ownership binding were durable, leaving
  a duplicate-generation window if local acquisition failed.
- Positive control: external R3 found the window before Trial A re-entry.
- Control added: the exact raw observation and verified authoritative binding
  are persisted before fetching bytes. An acquisition failure retains confirmed
  dispatch, confirmed attribution, and exact provider identity, with no
  selected asset and no authority for another Generate.

## Workflow lesson

A runtime goal that discovers a source defect must be explicitly dispositioned
before a source-assurance goal takes authority. Goal 21 revision 1 was aborted
with `BLOCK_SOURCE_DEFECT_REPLAY_REENTRY_VALIDATOR`, preserving its runtime
evidence and making a later Goal 21 revision the only permitted continuation.

`unpersisted_os_findings=0`

`unpersisted_orchestration_findings=0`
