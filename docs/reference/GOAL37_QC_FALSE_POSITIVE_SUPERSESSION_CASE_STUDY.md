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

## Legacy-state compatibility

Revision 2 adds a fail-closed compatibility proof for pre-Goal37 naturalness
rejections that did not persist `selected_asset_path` or
`selected_asset_sha256`. The old rejection is never edited. Reopen is possible
only when the current selected bytes validate, the caller supplies the matching
SHA-256, the latest review is the legacy naturalness rejection, and preserved
attempt/postprocess history proves one confirmed selected asset with no later
provider attempt, recovery, invalidation, rebinding, or replacement descendant.
The new `LEGACY_QC_REJECTION_ASSET_BINDING_RECONCILED` event records that proof
before returning the same bytes to ordinary QC.

Backward-compatible state-machine changes must test the exact persisted legacy
event shape production will resume from. A fixture created through the new
implementation can silently include fields unavailable in historical state and
hide a migration/compatibility defect. Risk-tiered review workflows should make
legacy-state compatibility an explicit check for state-transition changes.

## Workflow and Build OS lesson

Review and approval state machines need a bounded append-only supersession path.
Without one, a reviewer false positive becomes a source-code incident or forces
unnecessary regeneration. Rejection history is not the same as the current
authoritative disposition; a safe design preserves both.

Post-shipping Build OS improvement candidate: risk-tiered review systems should
model `REJECT -> APPEAL/REOPEN -> RE-REVIEW`, rather than force source mutation
or regeneration. Broader OS synthesis remains deferred until shipping.
