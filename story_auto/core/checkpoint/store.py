"""Small checkpoint store: only completed stages with present outputs are reusable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project.paths import ProjectPaths


@dataclass(frozen=True)
class StageDecision:
    action: str
    reason: str


class CheckpointStore:
    def __init__(self, project: ProjectPaths) -> None:
        self.project = project
        self.root = project.root / "output" / ".checkpoints"

    def _path(self, stage_name: str) -> Path:
        if not stage_name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("stage_name must be a simple stable identifier")
        return self.root / f"{stage_name}.json"

    def decide(self, stage_name: str, fingerprint: str) -> StageDecision:
        try:
            state = read_json(self._path(stage_name))
            if not isinstance(state, dict):
                return StageDecision("RUN", "corrupted checkpoint state")
            if state.get("status") != "SUCCESS":
                return StageDecision("RUN", "previous stage did not succeed")
            if state.get("fingerprint") != fingerprint:
                return StageDecision("RUN", "fingerprint changed")
            outputs = state.get("outputs")
            if not isinstance(outputs, list) or not outputs:
                return StageDecision("RUN", "checkpoint has no expected outputs")
            for output in outputs:
                if not isinstance(output, str) or not self.project.artifact_path(output).is_file():
                    return StageDecision("RUN", "expected output is missing or invalid")
            return StageDecision("SKIP", "matching successful checkpoint")
        except Exception:
            return StageDecision("RUN", "corrupted checkpoint state")

    def record(self, stage_name: str, *, fingerprint: str, status: str, outputs: list[str], producer_version: str) -> None:
        if status not in {"SUCCESS", "FAILED"}:
            raise ValueError("checkpoint status must be SUCCESS or FAILED")
        atomic_write_json(self._path(stage_name), {
            "schema_version": "story-auto-checkpoint/1.0.0", "fingerprint": fingerprint,
            "status": status, "outputs": outputs, "producer_version": producer_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
