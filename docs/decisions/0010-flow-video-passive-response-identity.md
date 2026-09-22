# Decision 0010 — Flow video response identity remains passive and experimental

Date: 2026-09-20
Status: ACCEPTED

## Context

The current Angular Flow video tile exposes only a thumbnail URL and no durable
job identifier in DOM attributes or accessible Angular state. Thumbnail bytes
changed after reload while the downloaded MP4 remained byte-identical, so URL,
thumbnail hash and gallery position cannot safely identify or recover a result.

Normal Flow project responses observed passively contain a repeated three-UUID
tuple adjacent to the rendered media token. The middle UUID equals the bound
Flow project identity. In one bounded canary, all three tuple components occurred
in the prompt-bound response chain; the tuple selected one exact tile and survived
reload while recovering the byte-identical MP4.

## Decision

1. Story Auto may passively observe responses initiated by the normal Flow UI;
   it must not construct, replay or mutate the observed RPC contract.
2. The observed tuple is named neutrally as component 1, project identity and
   component 3. The adapter must not claim undocumented `job_id` or `asset_id`
   semantics for the outer components.
3. Decoding is project-bound and bounded by body size, nesting/node count and
   response count. A token mapped to multiple tuples is ambiguous and fails
   closed.
4. Raw response bodies, cookies, auth headers, signed URLs and tuple values are
   not written by the diagnostic path. Diagnostic evidence output contains
   hashes only. The exact tuple may be written only to the canonical attempt
   ledger after project/request/attempt and confirmed-dispatch preconditions
   verify, because exact recovery requires the value rather than its hash.
5. The decoder and exact-tuple acquirer remain experimental provider-contract
   support, but may serve as canonical attempt authority when a sealed pre-click
   identity set, trusted activation epoch and unique rendered-video delta all
   verify. This does not change Full Video production routing.
6. After Flow visibly accepts one trusted VIDEO activation, Story Auto atomically
   persists the activation epoch and sealed pre-click identity set before waiting
   for output. This checkpoint remains unconfirmed and `retry_authorized=false`;
   it is recovery evidence for the same attempt, never permission to Generate
   again.

## Evidence

The pure decoder has provider-free positive, wrong-project, malformed-shape,
collision, non-media and resource-bound tests. Two independent live read-only
reloads of the isolated Flow project resolved all six rendered video tiles with
identical sanitized output, including the exact-lineage canary tuple. Both runs
recorded zero Generate activations and zero RPC replays.

One later live reload used the experimental acquirer to resolve the same six
tiles, select exactly one tile by the canary tuple, and download a validated
H.264/AAC 1280x720, 8.000-second MP4. Its SHA-256 matched the original canary
byte for byte. The acquisition path recorded zero Generate activations and zero
RPC replays and has no gallery-order fallback. Provider-free tests cover exact,
missing, duplicate and existing-destination refusal behavior.

The canonical attempt binding is provider-free qualified. It requires one
fingerprint-matched VIDEO request and attempt, the bound Flow project identity,
provider-boundary entry and a verified activation/output epoch. The binding is hash-sealed,
idempotent for the same tuple and rejects conflict, tamper or state regression.
Canonical recovery accepts project/request/attempt only and re-reads the binding
before provider observation and acquisition.

The exact dedicated Chrome process was closed and reopened through Story Auto.
All five identities visible before restart remained among the six visible after
restart; the canary stayed unique, and its downloaded MP4 remained byte-identical
to the original canary. The restart run used zero Generate activations and zero
RPC replays.

One later isolated canonical reference-to-video request exercised the full
ledger path. A trusted Playwright locator activation crossed Generate exactly
once. The result arrived after the 480-second foreground wait, so the attempt
first stopped `AMBIGUOUS` without adopting a gallery item. Read-only reload
evidence showed a unique bounded response-set delta containing one rendered
video identity plus one late reference-upload identity. Recovery reconstructed
the sealed pre-click fingerprint, required exactly one delta member to map to a
rendered video tile, persisted that exact tuple before acquisition, and completed
the same attempt with zero additional Generate activations and zero RPC replays.
The selected H.264/AAC 1280x720, 8.000-second MP4 has SHA-256
`7a4e3a57b287e7feedbce428ece8d2acf2f538081b2ed547ba6e04ecede20e3d`;
post-reload recovery reproduced it byte for byte.

A second isolated canary qualified the mid-generation interruption boundary.
Request `req_84ccd34db833d19d116a` persisted a 16-identity
`PROVIDER_ACCEPTED_AWAITING_OUTPUT` checkpoint after exactly one trusted Generate,
then the controlling client was interrupted. A fresh client later observed one
unique additional identity, persisted its binding before acquisition and completed
the original attempt with `provider_submissions=1`, `attempt_count=1`, and no
replacement activation. The H.264/AAC 1280x720, 8.000-second MP4 is 3,195,640
bytes with SHA-256
`40d43ecc5e5befcbd56478a4e130da45166b8588345e1b2d1326d7c9a51b866e`.
Independent persisted-binding recovery used zero Generate activations and zero
RPC replays and reproduced the same bytes. Evidence is under
`mid-generation-disconnect-16`.

Independent review identified one further crash window after exact tuple
persistence but before byte acquisition. The adapter now prioritizes recovery
from that already-bound tuple, revalidates the binding and finalizes the same
attempt without another Generate; a canonical provider-free crash fixture covers
this path. Review also left one acceptance boundary open: a transiently empty
prompt-editor projection plus a concurrent manual writer in the same Flow
project cannot yet be distinguished solely by passive response-set delta.

## Promotion gates

Automatic in-time binding, late-output recovery and one mid-generation client
interruption are qualified on isolated canonical requests. Unknown/changed
response shapes must continue to fail without gallery-order fallback or another
Generate. Production routing additionally requires representative unattended
sequential evidence, broader schema-drift coverage and an explicit routing
decision.
