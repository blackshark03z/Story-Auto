"""Conservative canonical-ID repair; never guess which group owns a boundary."""
from copy import deepcopy
import json


def repair_grouping(value: dict, canonical: list[str]) -> dict:
    candidate = deepcopy(value)
    groups = candidate.get("groups")
    if not isinstance(groups, list) or not groups or len(set(canonical)) != len(canonical):
        raise ValueError("nonempty groups and unique canonical IDs required")
    positions = {item: index for index, item in enumerate(canonical)}
    owners = {}
    for index, group in enumerate(groups):
        ids = group.get("segment_ids") if isinstance(group, dict) else None
        if not isinstance(ids, list) or not ids or any(not isinstance(item, str) for item in ids):
            raise ValueError("each group requires string segment_ids")
        for item in ids:
            if item not in positions:
                raise ValueError(f"unknown canonical ID: {item}")
            if item in owners and owners[item] != index:
                raise ValueError(f"conflicting group assignments: {item}")
            owners[item] = index
        group["segment_ids"] = sorted(set(ids), key=positions.__getitem__)
    # A group may fill only its own interior. Interleaving ownership is unsafe.
    for index, group in enumerate(groups):
        ids = group["segment_ids"]
        span = canonical[positions[ids[0]]:positions[ids[-1]] + 1]
        if any(item in owners and owners[item] != index for item in span):
            raise ValueError("interleaving groups")
        group["segment_ids"] = span
    groups.sort(key=lambda group: positions[group["segment_ids"][0]])
    if [item for group in groups for item in group["segment_ids"]] != canonical:
        raise ValueError("missing boundary IDs have no unique owner")
    return candidate


def defect_feedback(value: dict, canonical: list[str], detail: str) -> str:
    groups = value.get("groups", []) if isinstance(value, dict) else []
    ids = [item for group in groups if isinstance(group, dict)
           for item in (group.get("segment_ids") or []) if isinstance(item, str)]
    seen = set(ids)
    diagnostic = {"defect": detail, "missing": [item for item in canonical if item not in seen],
                  "duplicates": sorted({item for item in ids if ids.count(item) > 1}),
                  "unknown": sorted(seen - set(canonical)), "returned_order": ids}
    return "Return a complete corrected grouping in canonical order, each ID exactly once. " + json.dumps(diagnostic)
