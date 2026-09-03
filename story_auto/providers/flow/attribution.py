"""Pure request-epoch attribution rules for the Flow browser adapter."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


ATTRIBUTION_METHOD_VERSION = "flow-provider-model-card-lineage/2.0.0"


def provider_identity(record: dict[str, Any]) -> str:
    """Return a stable, non-secret identity for one provider-visible record."""
    card_id = str(record.get("card_id") or "").strip()
    asset_id = str(record.get("asset_id") or "").strip()
    if asset_id:
        return f"asset:{asset_id}"
    if card_id:
        return f"card:{card_id}"
    return ""


def evidence_identity(record: dict[str, Any]) -> dict[str, Any]:
    """Project a live DOM record to durable evidence without provider URLs."""
    return {
        "identity": provider_identity(record),
        "card_id": record.get("card_id"),
        "asset_id": record.get("asset_id"),
        "media_type": record.get("media_type"),
        "state": record.get("state"),
    }


def surface_fingerprint(records: list[dict[str, Any]]) -> str:
    projected = sorted(
        (evidence_identity(record) for record in records),
        key=lambda item: (
            str(item.get("identity") or ""),
            str(item.get("media_type") or ""),
            str(item.get("state") or ""),
        ),
    )
    payload = json.dumps(projected, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def records_for_type(records: list[dict[str, Any]], media_type: str) -> list[dict[str, Any]]:
    return [
        record for record in records
        if record.get("media_type") in {media_type, None}
    ]


@dataclass(frozen=True)
class AttributionObservation:
    state: str
    method: str
    candidate: dict[str, Any] | None
    lineage_card_id: str | None
    candidate_delta_count: int
    candidate_identities: list[dict[str, Any]]
    foreign_candidate_identities: list[dict[str, Any]]
    stable_polls: int
    causal_card_ids: list[str] | None = None
    within_group_selection_policy: str | None = None
    historical_alias_card_ids: list[str] | None = None


class RequestAttributionTracker:
    """Resolve one output only from the provider delta for one activation.

    Time and gallery order are deliberately absent from this state machine.
    A unique new tile can establish lineage; otherwise exactly one stable asset
    delta is the conservative fallback. Competing candidates before lineage is
    established are always ambiguous.
    """

    def __init__(self, baseline: list[dict[str, Any]], *, media_type: str,
                 expected_count: int, required_stable_polls: int = 3):
        if expected_count < 1 or required_stable_polls < 2:
            raise ValueError("invalid attribution contract")
        self.media_type = media_type
        self.expected_count = expected_count
        self.required_stable_polls = required_stable_polls
        typed = records_for_type(baseline, media_type)
        # Asset identity is the monotonic newness authority.  Media type is
        # only routing metadata, so a thumbnail or other representation seen
        # before activation must keep the same asset stale for this attempt.
        stable_assets = {
            provider_identity(record) for record in baseline
            if record.get("asset_id") and provider_identity(record)
        }
        self.baseline_identities = stable_assets | {
            provider_identity(record) for record in typed if provider_identity(record)
        }
        self.baseline_cards = {str(record.get("card_id")) for record in typed if record.get("card_id")}
        self.lineage_card_id: str | None = None
        self.lineage_identity: str | None = None
        self.lineage_from_pending = False
        self._candidate_signature: tuple[str, ...] | None = None
        self._stable_polls = 0

    def observe(self, current: list[dict[str, Any]], *, provider_busy: bool = False,
                causal_card_ids: set[str] | None = None,
                causal_anchor_final: bool = False) -> AttributionObservation:
        if causal_card_ids is not None:
            return self._observe_causal(
                current, causal_card_ids=causal_card_ids,
                causal_anchor_final=causal_anchor_final,
            )
        typed = records_for_type(current, self.media_type)
        ready = [record for record in typed if record.get("state") == "READY" and provider_identity(record)]
        pending = [record for record in typed if record.get("state") == "PENDING"]
        unseen = [record for record in ready if provider_identity(record) not in self.baseline_identities]
        all_new_cards = {
            str(record.get("card_id")) for record in typed
            if record.get("card_id")
            and str(record.get("card_id")) not in self.baseline_cards
            and (record.get("state") == "PENDING"
                 or (record.get("state") == "READY" and provider_identity(record) not in self.baseline_identities))
        }

        if self.lineage_card_id is None and self.lineage_identity is None:
            if len(all_new_cards) > 1 or len(unseen) > self.expected_count:
                return self._observation("AMBIGUOUS", None, unseen, [], 0)
            if len(all_new_cards) == 1:
                self.lineage_card_id = next(iter(all_new_cards))
                self.lineage_from_pending = any(
                    str(record.get("card_id") or "") == self.lineage_card_id
                    and record.get("state") == "PENDING"
                    for record in typed
                )
            elif len(unseen) == self.expected_count == 1:
                self.lineage_identity = provider_identity(unseen[0])

        if self.lineage_card_id is not None:
            lineage = [
                record for record in unseen
                if str(record.get("card_id") or "") == self.lineage_card_id
            ]
            foreign = [record for record in unseen if record not in lineage]
            if foreign and not self.lineage_from_pending:
                return self._observation("AMBIGUOUS", None, unseen, foreign, 0)
            lineage_pending = any(
                str(record.get("card_id") or "") == self.lineage_card_id
                for record in pending
            )
        elif self.lineage_identity is not None:
            lineage = [record for record in unseen if provider_identity(record) == self.lineage_identity]
            foreign = [record for record in unseen if record not in lineage]
            lineage_pending = False
            if foreign:
                return self._observation("AMBIGUOUS", None, unseen, [], 0)
        else:
            lineage, foreign, lineage_pending = [], unseen, False

        if provider_busy:
            self._candidate_signature = None
            self._stable_polls = 0
            return self._observation("WAITING", None, unseen, foreign, 0)

        if len(lineage) > self.expected_count:
            return self._observation("AMBIGUOUS", None, unseen, foreign, 0)
        if len(lineage) != self.expected_count or lineage_pending:
            self._candidate_signature = None
            self._stable_polls = 0
            return self._observation("WAITING", None, unseen, foreign, 0)

        signature = tuple(sorted(provider_identity(record) for record in lineage))
        if signature == self._candidate_signature:
            self._stable_polls += 1
        else:
            self._candidate_signature = signature
            self._stable_polls = 1
        state = "CONFIRMED" if self._stable_polls >= self.required_stable_polls else "CANDIDATE"
        return self._observation(state, lineage[0] if len(lineage) == 1 else None,
                                 unseen, foreign, self._stable_polls)

    def _observe_causal(self, current: list[dict[str, Any]], *,
                        causal_card_ids: set[str],
                        causal_anchor_final: bool) -> AttributionObservation:
        """Track only cards proven new by the complete provider model.

        The visible DOM is virtualized and may reinsert historical tiles.  Its
        records can describe a causally owned card's pending/ready lifecycle,
        but they cannot establish which card belongs to this activation.
        """
        causal = {str(value) for value in causal_card_ids if str(value)}
        typed = records_for_type(current, self.media_type)
        ready = [record for record in typed
                 if record.get("state") == "READY" and provider_identity(record)]
        pending = [record for record in typed if record.get("state") == "PENDING"]
        historical_aliases = {
            card_id for card_id in causal
            if (
                any(str(record.get("card_id") or "") == card_id for record in ready)
                and not any(str(record.get("card_id") or "") == card_id for record in pending)
                and all(
                    provider_identity(record) in self.baseline_identities
                    for record in ready
                    if str(record.get("card_id") or "") == card_id
                )
            )
        }
        causal -= historical_aliases
        causal_ready = [record for record in ready
                        if str(record.get("card_id") or "") in causal]
        foreign = [record for record in ready
                   if str(record.get("card_id") or "") not in causal
                   and provider_identity(record) not in self.baseline_identities]

        if len(causal) > self.expected_count:
            return self._observation(
                "AMBIGUOUS", None, causal_ready, foreign, 0,
                causal_card_ids=causal, historical_alias_card_ids=historical_aliases,
            )
        if not causal:
            self._candidate_signature = None
            self._stable_polls = 0
            return self._observation(
                "AMBIGUOUS" if causal_anchor_final else "WAITING",
                None, [], foreign, 0, causal_card_ids=causal,
                historical_alias_card_ids=historical_aliases,
            )
        if len(causal) != self.expected_count or self.expected_count != 1:
            self._candidate_signature = None
            self._stable_polls = 0
            return self._observation(
                "AMBIGUOUS" if causal_anchor_final else "WAITING",
                None, causal_ready, foreign, 0, causal_card_ids=causal,
                historical_alias_card_ids=historical_aliases,
            )

        causal_card_id = next(iter(causal))
        if self.lineage_card_id not in {None, causal_card_id}:
            return self._observation(
                "AMBIGUOUS", None, causal_ready, foreign, 0,
                causal_card_ids=causal, historical_alias_card_ids=historical_aliases,
            )
        self.lineage_card_id = causal_card_id
        lineage_pending = any(
            str(record.get("card_id") or "") == causal_card_id
            for record in pending
        )
        if not causal_ready or lineage_pending:
            self._candidate_signature = None
            self._stable_polls = 0
            return self._observation(
                "WAITING", None, causal_ready, foreign, 0,
                causal_card_ids=causal, historical_alias_card_ids=historical_aliases,
            )

        ordered = sorted(causal_ready, key=provider_identity)
        signature = tuple(provider_identity(record) for record in ordered)
        if signature == self._candidate_signature:
            self._stable_polls += 1
        else:
            self._candidate_signature = signature
            self._stable_polls = 1
        state = "CONFIRMED" if self._stable_polls >= self.required_stable_polls else "CANDIDATE"
        policy = (
            "LEXICOGRAPHIC_PROVIDER_IDENTITY_WITHIN_CAUSAL_GROUP"
            if len(ordered) > 1 else "EXACT_CAUSAL_CARD_SINGLE_ASSET"
        )
        return self._observation(
            state, ordered[0], ordered, foreign, self._stable_polls,
            causal_card_ids=causal, within_group_selection_policy=policy,
            historical_alias_card_ids=historical_aliases,
        )

    def _observation(self, state: str, candidate: dict[str, Any] | None,
                     candidates: list[dict[str, Any]], foreign: list[dict[str, Any]],
                     stable_polls: int, *, causal_card_ids: set[str] | None = None,
                     within_group_selection_policy: str | None = None,
                     historical_alias_card_ids: set[str] | None = None) -> AttributionObservation:
        return AttributionObservation(
            state=state,
            method=ATTRIBUTION_METHOD_VERSION,
            candidate=candidate,
            lineage_card_id=self.lineage_card_id,
            candidate_delta_count=len(candidates),
            candidate_identities=[evidence_identity(record) for record in candidates],
            foreign_candidate_identities=[evidence_identity(record) for record in foreign],
            stable_polls=stable_polls,
            causal_card_ids=(sorted(causal_card_ids) if causal_card_ids is not None else None),
            within_group_selection_policy=within_group_selection_policy,
            historical_alias_card_ids=(
                sorted(historical_alias_card_ids)
                if historical_alias_card_ids is not None else None
            ),
        )
