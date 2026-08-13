"""Production naturalness review rules; technical validation remains provider-local."""
from __future__ import annotations

from typing import Any

NATURALNESS_QC_FIELDS = (
    "SKIN_REALISM",
    "LIGHTING_NATURALISM",
    "MATERIAL_REALISM",
    "COMPOSITION_NATURALISM",
    "AI_POLISH",
    "CONTINUITY",
    "TECHNICAL_VALIDITY",
)
_RESULTS = {"PASS", "FAIL", "NOT_APPLICABLE"}


class MediaQualityError(ValueError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def validate_production_qc(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise MediaQualityError("MEDIA_QC_INVALID")
    results = report.get("results")
    if not isinstance(results, dict) or set(results) != set(NATURALNESS_QC_FIELDS):
        raise MediaQualityError("MEDIA_QC_INVALID", "all naturalness fields are required")
    if any(value not in _RESULTS for value in results.values()):
        raise MediaQualityError("MEDIA_QC_INVALID")
    if report.get("visible_provider_watermark") is not False:
        raise MediaQualityError("VISIBLE_PROVIDER_WATERMARK")
    failures = [field for field, value in results.items() if value == "FAIL"]
    if failures:
        raise MediaQualityError("NATURALNESS_QC_REJECTED", ",".join(failures))
    reviewer = report.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise MediaQualityError("MEDIA_QC_INVALID", "reviewer is required")
    return {
        "results": dict(results),
        "visible_provider_watermark": False,
        "reviewer": reviewer.strip(),
        "notes": str(report.get("notes", "")).strip(),
    }
