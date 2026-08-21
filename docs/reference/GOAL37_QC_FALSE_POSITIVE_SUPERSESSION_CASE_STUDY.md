# Goal 37: QC false-positive supersession

## Product problem

Production naturalness QC can correctly reject an asset, but a reviewer can
also make a false-positive decision. Previously, a
`NATURALNESS_QC_REJECTED` selected asset had no safe appeal path: it could not
return to ordinary production QC without generating a replacement. That made a
review error terminal even when the exact, confirmed-attribution bytes were
still available.

## Bounded transition

Goal 37 adds one append-only operation: reopen an exact rejected selected asset
for a second ordinary production-QC decision. It requires the current
`FAILED_RETRYABLE` / `NATURALNESS_QC_REJECTED` state, a caller-supplied matching
SHA-256, valid local bytes, and the latest rejection review bound to those same
bytes. The operation records `FALSE_POSITIVE_REOPENED` with the reviewer,
reason, asset identity, rejection index, and deterministic rejection hash.

It does not mark the asset passed, change the rejection record, submit to Flow,
create a replacement, replay an earlier request, or modify live Trial A data.
The only resulting disposition is `QC_PENDING` with `production_qc=PENDING`.
The normal QC operation must still make the next pass or fail decision, with
technical validation, visual-narration alignment, temporal video QC, and
watermark rules intact.

## Workflow and Build OS lesson

Review and approval state machines need a bounded append-only supersession path.
Without one, a reviewer false positive becomes a source-code incident or forces
unnecessary regeneration. Rejection history is not the same as the current
authoritative disposition; a safe design preserves both.

Post-shipping Build OS improvement candidate: risk-tiered review systems should
model `REJECT -> APPEAL/REOPEN -> RE-REVIEW`, rather than force source mutation
or regeneration. Broader OS synthesis remains deferred until shipping.
