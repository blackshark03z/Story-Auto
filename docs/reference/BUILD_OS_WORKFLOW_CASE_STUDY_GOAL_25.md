# Goal 25 — Safety semantics must have one enforcement authority

## Product case study

- Title: Safety semantics must have one enforcement authority.
- Classification: `PRODUCT ARCHITECTURE / SPEC / WORKFLOW`.
- Verified failure: the provider retry gate accepted a verified
  legacy-equivalent no-dispatch proof while the abandoned-replay validator
  independently required only the newer representation and rejected the same
  attempt.
- Reusable rule: evidence representations may evolve, but safety-critical
  consumers must depend on one semantic authority rather than interpret schemas
  independently.

`canonical_no_dispatch_proof(attempt)` is the sole semantic authority for the
question, “does this persisted attempt positively prove that no provider
dispatch occurred?” It accepts only a strict current activation proof or a
strict verified legacy-equivalent poll timeline. All other evidence fails
closed.

Safety-critical consumers are the provider retry gate, abandoned-replay
validator, queue barrier, and execution re-entry boundary. Low-level helpers
remain schema-specific evidence validators; status-only workflows such as local
repair and operator recovery do not cross the provider boundary and remain
subject to the execution gate.

## Deferred Build OS and workflow findings

1. Product commit must not precede its durable Goal lifecycle record.
2. Canonical Build OS has no owner-authorized adopt-existing-descendant
   primitive.
3. Admin new-revision operates only on the current durable record and cannot
   target an older terminal Goal.
4. No truthful public block-and-release operation exists for a runtime Goal
   that discovers a source defect; current recovery required bounded
   Owner-authorized admin abort.

Classification: `BUILD_OS / WORKFLOW / DISCOVERABILITY`.

No Build OS implementation was modified for these findings.

`unpersisted_os_findings=0`

`unpersisted_orchestration_findings=0`

## Revision 2 corrective finding

- Title: Safety producers and consumers must share the same semantic proof.
- Classification: `PRODUCT ARCHITECTURE / SPEC`.
- Verified failure: a recovery path could classify an interrupted attempt as
  safely `NOT_DISPATCHED`, while the canonical semantic authority could not
  verify that classification on subsequent re-entry.
- Reusable rule: any component that produces a safety-relevant state must
  persist or verify the same semantic evidence consumed by downstream safety
  gates.
- Positive control: external R3 found the recoverability contradiction before
  Trial A runtime resumed.

Revision 2 persists `provider_execution_state=NOT_STARTED` with every submitted
attempt, then durably records `PROVIDER_BOUNDARY_ENTERED` immediately before
the only provider invocation. Only the former state may be converted into the
normal current-schema activation proof. Crashes after that boundary, ambiguous
crash points, and status-only records fail closed. The reopen helpers now also
require `canonical_no_dispatch_proof(attempt)` rather than declaring a separate
retry authority.

### Revision-2 Flow source audit

| Classification | Flow ownership |
| --- | --- |
| Evidence producers | Live adapter activation evidence; ordered crash recovery; external reconciliation evidence. Every producer persists the current-schema proof and verifies `canonical_no_dispatch_proof` before releasing a barrier. |
| Evidence verifiers | Current activation validator, verified legacy-timeline validator, and their one semantic wrapper `canonical_no_dispatch_proof`. |
| Semantic consumers | Provider retry authorization, abandoned-replay validation, queue-barrier detection, execution re-entry, and both reopen helpers. |
| Unrelated lifecycle state | `SUBMITTED`, `GENERATING`, `FAILED_RETRYABLE`, local postprocess recovery, manual asset adoption, and status projection remain diagnostic or local-only; none crosses the provider boundary without the canonical retry gate. |

No producer can authorize from `NOT_DISPATCHED`, `dispatch_confirmed=False`,
`provider_settings=None`, `SUBMITTED`, or `GENERATING` alone.
