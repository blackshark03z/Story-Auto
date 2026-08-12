"""Fail-closed Flow composer page object, intentionally small and fixture-testable."""
from __future__ import annotations

from .session import FlowSessionError


class FlowComposer:
    def __init__(self, dom): self.dom = dom

    def _one(self, name: str, values):
        if len(values) != 1: raise FlowSessionError("FLOW_UI_CHANGED", f"expected exactly one {name}, found {len(values)}")
        return values[0]

    def submit(self, prompt: str, *, references: list[str], media_type: str) -> None:
        editors = self.dom.active_prompt_editors()
        editor = self._one("active prompt editor", editors)
        editor.set_text(prompt)
        if editor.read_text() != prompt: raise FlowSessionError("FLOW_UI_CHANGED", "prompt readback mismatch")
        if references: self.dom.add_references(references)
        controls = self.dom.generate_controls(editor, media_type)
        control = self._one("active composer Generate control", controls)
        control.click()

    def candidates(self): return self.dom.media_candidates()
