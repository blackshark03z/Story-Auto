"""Durable editorial quality-review policy for a project.

Technical asset/provenance validation remains owned by the generation service.
This module only resolves the project-level editorial policy and preserves the
legacy manual-review behaviour for projects that predate the setting.
"""
from __future__ import annotations

from typing import Any


AUTO_ACCEPT = "AUTO_ACCEPT"
MANUAL_REVIEW = "MANUAL_REVIEW"
AI_REVIEW = "AI_REVIEW"
QC_POLICIES = frozenset({AUTO_ACCEPT, MANUAL_REVIEW, AI_REVIEW})
RUNNABLE_QC_POLICIES = frozenset({AUTO_ACCEPT, MANUAL_REVIEW})
QC_POLICY_SETTING = "qc_policy"


class QualityPolicyError(ValueError):
    failure_class = "QC_POLICY_INVALID"


def validate_qc_policy(value: Any) -> str:
    if value not in QC_POLICIES:
        raise QualityPolicyError("QC_POLICY_INVALID")
    return str(value)


def effective_qc_policy(settings: dict[str, Any]) -> tuple[str, bool]:
    """Return policy and whether it was explicitly persisted on this project.

    Historical projects have no policy.  They intentionally retain the former
    manual gate until an operator explicitly changes their project setting.
    """
    raw = settings.get(QC_POLICY_SETTING)
    if raw is None:
        return MANUAL_REVIEW, False
    return validate_qc_policy(raw), True


def settings_with_default_qc_policy(settings: dict[str, Any]) -> dict[str, Any]:
    """Persist the runtime default for a newly created project only."""
    if QC_POLICY_SETTING in settings:
        validate_qc_policy(settings[QC_POLICY_SETTING])
        return dict(settings)
    return {**settings, QC_POLICY_SETTING: AUTO_ACCEPT}
