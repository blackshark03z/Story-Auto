"""Fail-closed Flow composer page object, intentionally small and fixture-testable."""
from __future__ import annotations

from .session import FlowSessionError


class FlowComposer:
    def __init__(self, dom): self.dom = dom

    def _one(self, name: str, values):
        if len(values) != 1: raise FlowSessionError("FLOW_UI_CHANGED", f"expected exactly one {name}, found {len(values)}")
        return values[0]

    def submit(self, prompt: str, *, references: list[str], media_type: str, before_dispatch=None, mode_already_configured: bool = False) -> dict:
        choose = getattr(self.dom, "choose_mode", None)
        if choose and not mode_already_configured: choose(media_type)
        editors = self.dom.active_prompt_editors()
        editor = self._one("active prompt editor", editors)
        editor.set_text(prompt)
        if editor.read_text() != prompt: raise FlowSessionError("FLOW_UI_CHANGED", "prompt readback mismatch")
        reference_state = {"expected": len(references), "committed": not references, "method": "not_required"}
        if references:
            observed = self.dom.add_references(references)
            if isinstance(observed, dict): reference_state.update(observed)
            else: reference_state.update({"committed": True, "method": "adapter_completed"})
            if not reference_state.get("committed"):
                raise FlowSessionError("FLOW_REFERENCE_UPLOAD_FAILED", "reference attachment was not committed")
        controls = self.dom.generate_controls(editor, media_type)
        control = self._one("active composer Generate control", controls)
        composer_ready_state = {
            "prompt_committed": True,
            "reference_state": reference_state,
            "generate_enabled": bool(getattr(control, "evidence", {}).get("enabled", True)),
        }
        setattr(self.dom, "last_composer_ready_state", composer_ready_state)
        # Reference attachment itself changes Flow's UI.  The caller may take
        # its dispatch baseline only after that benign transition is complete.
        if before_dispatch: before_dispatch()
        activation = control.click()
        return {"composer_ready_state": composer_ready_state, "activation": activation}

    def candidates(self): return self.dom.media_candidates()
