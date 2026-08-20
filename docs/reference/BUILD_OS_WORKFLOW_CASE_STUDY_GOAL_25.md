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
