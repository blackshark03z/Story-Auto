# ADR-006: Flow image postprocessing

Status: Accepted

## Context

The historical v1.0.0 policy retained the visible Google Flow sparkle mark for
both images and videos as an accepted provider limitation. After v1.0.0, the
owner amended the production-image policy: a Flow image with a remaining visible
mark is not eligible for production selection. The historical v1.0.0 release
and tag remain immutable evidence of the policy in force at that release.

Flow video is outside this amendment. Its visible mark remains the accepted
limitation, and the existing safe-area and subtitle-clearance policies remain.

## Decision

Flow-specific image cleanup lives in the Flow provider adapter. For a
`STANDARD_PRODUCTION` image, the adapter:

1. acquires and technically validates the provider result;
2. preserves that provider-original file and SHA-256 as the successful raw
   provider attempt;
3. selects a versioned geometry profile for a verified Flow output size;
4. generates a deterministic procedural sparkle mask;
5. runs FFmpeg `removelogo` locally and validates the resulting image; and
6. binds `generation_manifest.selected_asset` to the clean derivative path and
   SHA-256.

The manifest remains schema-compatible with v1.0.0. An additive
`postprocess_attempts` ledger records the processing attempt, raw provider
attempt number/path/hash, derivative path/hash, processor and profile versions,
mask/profile fingerprints, timestamps, and any local failure class.

Raw Flow bytes are immutable. The renderer, compositor, image compiler, and UI
do not contain watermark-removal behavior; downstream systems continue to
resolve exactly `selected_asset.path` and `selected_asset.sha256`.

Supported image geometries fail closed through versioned profiles. An unknown
geometry is a local postprocessing failure, not permission to guess a repair
region.

## Recovery and reuse

A successful Flow acquisition followed by failed cleanup remains a successful
raw provider attempt. Resume, reconciliation, manual recovery, and the existing
retry/requeue path first rebuild the derivative from that raw file. A missing or
corrupt derivative with valid raw evidence causes zero new provider submissions.

Exact reuse accepts either legacy `raw == selected` lineage or explicit
`raw -> postprocess -> selected derivative` lineage. Reused production bytes are
still subject to fresh semantic/production QC. Reference dependencies resolve
from the clean selected path/hash, never from the branded raw file.

## Consequences

- Production Flow images with a reported visible provider mark fail QC.
- Production Flow videos retain the historical accepted limitation.
- Raw and selected bytes have separately verifiable paths and hashes.
- Local cleanup can be retried deterministically without paid/provider work.
- The bottom-right prompt safe area remains useful because video still carries
  the mark and image repair is safest away from critical content.
