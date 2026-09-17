# Decision 0007 — Provider key pool append semantics

Date: 2026-09-17
Status: Accepted

## Context

Story Auto already stores provider credentials as DPAPI-protected pools, but the Settings save actions replace the whole stored pool with one key. That makes adding a second key destructive and contradicts the pool abstraction.

## Decision

- Reuse the existing `story_auto.providers.credentials` DPAPI store as the single credential authority.
- Settings accepts a batch of provider keys (one key per line) for BytePlus, Elyum, and Pexels.
- Save means **append + stable-order dedupe**, never replace. The complete incoming batch is validated before any write.
- The UI exposes only non-secret metadata: configured state, credential source, and stored-key count. Key text, suffixes, hashes, and masked values are not projected.
- Removing saved keys clears the entire Story Auto DPAPI pool for that provider. Environment credentials are external authority and are not modified.
- Runtime provider selection/key rotation remains provider-adapter behavior; this slice changes credential persistence/UX only.

## Invariants

1. Adding a key cannot delete an already-saved key.
2. Adding the same key again is idempotent.
3. Invalid input causes no partial pool mutation.
4. Stored plaintext must never appear in project files, repo files, logs, or Settings API responses.
5. Existing single-key API clients remain compatible.
