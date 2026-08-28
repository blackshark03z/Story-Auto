"""Canonical pipeline execution intent and dependency-aware stage policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EXECUTION_MODES = frozenset({"FULL", "EXISTING_VOICE", "VISUALS_ONLY", "RENDER_ONLY"})


class ExecutionPolicyError(ValueError):
    failure_class = "EXECUTION_PREREQUISITE_MISSING"


@dataclass(frozen=True)
class StagePolicy:
    stage: str
    action: str
    reason: str | None = None


def execution_mode(settings: dict[str, Any]) -> str:
    value = settings.get("execution", {})
    if value is None:
        value = {}
    if not isinstance(value, dict) or not set(value).issubset({"mode"}):
        raise ExecutionPolicyError("settings.execution has unsupported fields")
    mode = value.get("mode", "FULL")
    if mode not in EXECUTION_MODES:
        raise ExecutionPolicyError("settings.execution.mode must be FULL, EXISTING_VOICE, VISUALS_ONLY, or RENDER_ONLY")
    return mode


def stage_policy(mode: str, *, has_valid_audio: bool, has_accepted_visuals: bool) -> dict[str, StagePolicy]:
    """Decide every stage explicitly; reuse always needs a validated artifact."""
    if mode not in EXECUTION_MODES:
        raise ExecutionPolicyError("EXECUTION_MODE_INVALID")
    audio = StagePolicy("audio", "RUN")
    planning = StagePolicy("planning", "RUN")
    visuals = StagePolicy("visuals", "RUN")
    render = StagePolicy("render", "RUN")
    if mode in {"EXISTING_VOICE", "VISUALS_ONLY", "RENDER_ONLY"}:
        audio = StagePolicy("audio", "REUSE" if has_valid_audio else "BLOCK", None if has_valid_audio else "No narration audio has been selected.")
    if mode == "RENDER_ONLY":
        planning = StagePolicy("planning", "REUSE" if has_valid_audio else "BLOCK", None if has_valid_audio else "No valid narration audio is available for the current plan.")
        visuals = StagePolicy("visuals", "REUSE" if has_accepted_visuals else "BLOCK", None if has_accepted_visuals else "No accepted visual assets are available for the current plan.")
    return {item.stage: item for item in (audio, planning, visuals, render)}
