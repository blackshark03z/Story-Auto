# Goal 23 — Retained evidence requires semantic compatibility, not history rewrites

## Lifecycle gap

- Title: Terminal Goal continuation requires an unavailable public new-revision capability.
- Classification: `BUILD_OS / WORKFLOW / DISCOVERABILITY`.
- Verified facts: canonical bootstrap rejects reuse of the terminal Goal21 task ID;
  it explicitly requires `new-revision`; that capability is admin-only; the
  approved public executor does not expose it; and the worker correctly refused
  to invent a substitute Goal.
- Reusable improvement candidate: expose an authorized public continuation
  operation, or an explicit owner-authorized admin escalation path for terminal
  revision continuation.

No Build OS implementation was modified for this finding.

## Product case study

- Title: Schema evolution must preserve semantic proof compatibility for retained runtime evidence.
- Classification: `PRODUCT ARCHITECTURE / SPEC`.
- Context: Goal22 strengthened provider retry authority after Goal21 had already
  retained a safe pre-dispatch attempt under an older evidence location.
- Positive control: the new source initially failed closed instead of treating
  the partially compatible record as safe automatically.
- Reusable rule: a new safety contract must either explicitly verify equivalent
  historical evidence or fail closed. It must never synthesize missing proof.

Goal23's compatibility reader accepts the historical form only when its complete
hash-chained poll timeline verifies and every observation remains pre-dispatch,
records `input_dispatched=false`, and has no dispatch or attribution authority.
It projects that fact into the same positive no-dispatch proof as the current
activation field. The reader never changes Trial A bytes or historical attempts.

`unpersisted_os_findings=0`

`unpersisted_orchestration_findings=0`
