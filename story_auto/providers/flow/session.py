"""Dedicated, operator-managed Chrome/CDP session discovery for Google Flow."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen
import json


@dataclass(frozen=True)
class FlowRuntime:
    profile: Path
    cdp_url: str
    project_url: str
    project_identity: str

    @classmethod
    def from_settings(cls, runtime, settings: dict) -> "FlowRuntime":
        flow = settings.get("flow", {}) if isinstance(settings, dict) else {}
        return cls(runtime.flow_profile, str(flow.get("cdp_url", "http://127.0.0.1:9222")),
                   str(flow.get("project_url", "https://labs.google/fx/tools/flow")),
                   str(flow.get("project_identity", "story-auto")))


@dataclass(frozen=True)
class FlowCapabilities:
    authenticated: bool
    project_ok: bool
    image: bool
    video: bool
    reference_image: bool
    frame_video: bool
    detail: str = ""

    def require(self, media_type: str, references: bool) -> None:
        if not self.authenticated: raise FlowSessionError("FLOW_AUTH_REQUIRED", "Sign in to Google in the dedicated Story Auto Flow profile, then resume.")
        if not self.project_ok: raise FlowSessionError("FLOW_PROJECT_MISMATCH", self.detail)
        if media_type == "IMAGE" and not self.image: raise FlowSessionError("FLOW_CAPABILITY_UNAVAILABLE", "image generation unavailable")
        if media_type == "VIDEO" and not self.video: raise FlowSessionError("FLOW_CAPABILITY_UNAVAILABLE", "video generation unavailable")
        if references and not (self.reference_image if media_type == "IMAGE" else self.frame_video):
            raise FlowSessionError("FLOW_REFERENCE_VIDEO_CAPABILITY_BLOCKED" if media_type == "VIDEO" else "FLOW_CAPABILITY_UNAVAILABLE", "reference input unavailable")


class FlowSessionError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = ""):
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def cdp_health(runtime: FlowRuntime, opener=urlopen) -> dict:
    try:
        with opener(runtime.cdp_url.rstrip("/") + "/json/version", timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict) or "Browser" not in data: raise ValueError("invalid CDP metadata")
        return data
    except Exception as error:
        raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "start Chrome with the Story Auto debugging profile") from error


def preflight(runtime: FlowRuntime, inspector, *, opener=urlopen) -> FlowCapabilities:
    """Live capability discovery delegated to a page inspector, never version assumptions."""
    cdp_health(runtime, opener)
    found = inspector.inspect(runtime.project_url)
    if found.get("login_required"):
        return FlowCapabilities(False, False, False, False, False, False, "interactive login required")
    project_ok = found.get("project_identity") == runtime.project_identity
    return FlowCapabilities(True, project_ok, bool(found.get("image")), bool(found.get("video")),
                            bool(found.get("reference_image")), bool(found.get("frame_video")),
                            "" if project_ok else "configured Flow project/workspace is not active")
