"""Pure request-epoch attribution rules for the Flow browser adapter."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


ATTRIBUTION_METHOD_VERSION = "flow-provider-tile-lineage/1.0.0"


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
        self.baseline_identities = {provider_identity(record) for record in typed if provider_identity(record)}
        self.baseline_cards = {str(record.get("card_id")) for record in typed if record.get("card_id")}
        self.lineage_card_id: str | None = None
        self.lineage_identity: str | None = None
        self.lineage_from_pending = False
        self._candidate_signature: tuple[str, ...] | None = None
        self._stable_polls = 0

    def observe(self, current: list[dict[str, Any]], *, provider_busy: bool = False) -> AttributionObservation:
        typed = records_for_type(current, self.media_type)
        ready = [record for record in typed if record.get("state") == "READY" and provider_identity(record)]
        pending = [record for record in typed if record.get("state") != "READY"]
        unseen = [record for record in ready if provider_identity(record) not in self.baseline_identities]
        all_new_cards = {
            str(record.get("card_id")) for record in typed
            if record.get("card_id")
            and str(record.get("card_id")) not in self.baseline_cards
            and (record.get("state") != "READY" or provider_identity(record) not in self.baseline_identities)
        }

        if self.lineage_card_id is None and self.lineage_identity is None:
            if len(all_new_cards) > 1 or len(unseen) > self.expected_count:
                return self._observation("AMBIGUOUS", None, unseen, [], 0)
            if len(all_new_cards) == 1:
                self.lineage_card_id = next(iter(all_new_cards))
                self.lineage_from_pending = any(
                    str(record.get("card_id") or "") == self.lineage_card_id
                    and record.get("state") != "READY"
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

    def _observation(self, state: str, candidate: dict[str, Any] | None,
                     candidates: list[dict[str, Any]], foreign: list[dict[str, Any]],
                     stable_polls: int) -> AttributionObservation:
        return AttributionObservation(
            state=state,
            method=ATTRIBUTION_METHOD_VERSION,
            candidate=candidate,
            lineage_card_id=self.lineage_card_id,
            candidate_delta_count=len(candidates),
            candidate_identities=[evidence_identity(record) for record in candidates],
            foreign_candidate_identities=[evidence_identity(record) for record in foreign],
            stable_polls=stable_polls,
        )
