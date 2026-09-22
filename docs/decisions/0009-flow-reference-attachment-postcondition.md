# Decision 0009 — Flow reference attachment uses a content-bound postcondition

Date: 2026-09-20
Status: ACCEPTED

## Context

The current Flow media picker can contain multiple overlay layers. Its Add
activation may time out or report an exception even after the intended asset has
already committed to the composer. Conversely, a selected-looking tile or a
closed dialog does not prove that the intended reference is attached. Treating
UI action return values as the oracle creates both blind retries and false
success before the consequential Generate action.

Direct in-page fetch and canvas extraction are not reliable on the observed Flow
asset surface. The existing attached browser session can read the displayed
asset bytes without exporting authentication material.

## Decision

1. Reference attachment is accepted only when the composer contains exactly one
   image whose perceptual content matches the requested local reference.
2. The adapter searches the structural media-picker overlay rather than assuming
   that the first generic overlay is authoritative.
3. Media bytes may be read through the existing authenticated browser session
   only from a narrow allowlist of observed Flow/Google asset hosts, with bounded
   count and size. Cookies, tokens and browser authentication state are never
   exported, persisted or logged.
4. Add is activated at most once for one attachment attempt. If activation
   reports an exception or timeout, the adapter reconciles the composer
   postcondition before deciding success or failure; it does not blindly retry.
5. Picker closure, selected styling, element text and click return status are
   supporting observations only. Zero, wrong or multiple composer images fail
   closed with `FLOW_REFERENCE_UPLOAD_FAILED` before Generate.
6. This decision qualifies the attachment step only. It does not accept Flow
   VIDEO as a production provider or change the API-first Full Video route.

## Evidence boundary

A provider-free 20/20 picker cycle and 20/20 mention-assisted cycle observed the
same exact-reference postcondition, including cases where Add activation itself
reported an exception. A canonical live no-Generate canary then confirmed one
exact composer image and stable cleanup through the implemented adapter. Focused
Flow and full Git-tracked test suites passed.

A separate bounded three-shot VIDEO smoke run produced three technically valid,
distinct eight-second MP4 downloads with the same exact reference. It did not by
itself prove durable provider job identity or exact request-to-output binding.
A later one-shot canary passively correlated the prompt-bound response chain to
one unique three-UUID result tuple, selected that exact mapped tile, downloaded a
valid MP4, and after reload recovered the same tuple and byte-identical MP4.
Thumbnail bytes changed across reload, so thumbnail identity is explicitly not a
recovery oracle. The tuple still comes from an observed, undocumented response
shape. Canonical integration, mid-generation client interruption and browser
restart have since been tested separately (Decision `0010`), but a later bounded
unattended run stopped before Generate on a new reference-attachment failure.
The current composer had no attached image on read-only inspection. This preserves
the fail-closed invariant but leaves repeatability and unattended production
reliability unqualified.

## Consequences and revisit triggers

The adapter may safely distinguish an action-layer exception from a failed
attachment without issuing a duplicate Add. It incurs bounded media reads and
perceptual comparison at the provider boundary, while core planning remains
provider-independent.

Revisit this decision if Flow exposes a supported asset identifier/content hash,
changes its picker/composer surface, or provides a documented API with durable
reference and job identity. A video-routing decision requires separate evidence
for result attribution and recovery.
