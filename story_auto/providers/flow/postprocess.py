"""Deterministic local cleanup for supported Google Flow image outputs.

Provider originals are inputs only.  This module always writes a distinct
derivative and fails closed when the Flow mark geometry is not known.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

from story_auto.core.artifacts import sha256_file
from .validation import AssetValidationError, validate_image


PROCESSOR_NAME = "flow-image-removelogo"
PROCESSOR_VERSION = "1.0.0"


@dataclass(frozen=True)
class FlowMarkProfile:
    version: str
    width: int
    height: int
    center_x: int
    center_y: int
    radius_x: int
    radius_y: int
    dilation: int = 2


PROFILES: dict[tuple[int, int], FlowMarkProfile] = {
    (1376, 768): FlowMarkProfile("flow-sparkle-1376x768-v1", 1376, 768, 1278, 671, 29, 27),
    (1280, 720): FlowMarkProfile("flow-sparkle-1280x720-v1", 1280, 720, 1160, 599, 27, 26),
}


class FlowImagePostprocessError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def supported_profiles() -> tuple[str, ...]:
    return tuple(profile.version for profile in PROFILES.values())


def profile_evidence(width: int, height: int) -> dict[str, str]:
    profile = PROFILES.get((width, height))
    if profile is not None:
        return {"profile_version": profile.version, "profile_sha256": _profile_fingerprint(profile)}
    version = f"unsupported-{width}x{height}"
    return {"profile_version": version,
            "profile_sha256": hashlib.sha256(version.encode("utf-8")).hexdigest()}


def _profile_fingerprint(profile: FlowMarkProfile) -> str:
    payload = json.dumps(asdict(profile), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_mask(path: Path, profile: FlowMarkProfile) -> str:
    """Write a compact full-frame mask around the four-point sparkle."""
    mask = Image.new("L", (profile.width, profile.height), 0)
    draw = ImageDraw.Draw(mask)
    cx, cy, rx, ry = profile.center_x, profile.center_y, profile.radius_x, profile.radius_y
    # The measured 35% shoulders cover the antialiased sparkle while keeping
    # the repair boundary off nearby scene structure.  Narrower shoulders leave
    # logo pixels behind; a full ellipse needlessly blurs crossing edges.
    sx, sy = max(2, round(rx * .35)), max(2, round(ry * .35))
    draw.polygon([
        (cx, cy - ry), (cx + sx, cy - sy), (cx + rx, cy), (cx + sx, cy + sy),
        (cx, cy + ry), (cx - sx, cy + sy), (cx - rx, cy), (cx - sx, cy - sy),
    ], fill=255)
    if profile.dilation:
        mask = mask.filter(ImageFilter.MaxFilter(profile.dilation * 2 + 1))
    mask.save(path, "PNG", optimize=False)
    return sha256_file(path)


def process_flow_image(source: Path, output: Path, *, runner=subprocess.run) -> dict[str, Any]:
    """Create and validate one clean derivative from an immutable Flow image."""
    source = Path(source)
    output = Path(output)
    try:
        if source.resolve() == output.resolve():
            raise FlowImagePostprocessError("FLOW_IMAGE_POSTPROCESS_OUTPUT_CONFLICT")
        source_metadata = validate_image(source)
    except FlowImagePostprocessError:
        raise
    except AssetValidationError as error:
        raise FlowImagePostprocessError("FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID") from error

    profile = PROFILES.get((source_metadata["width"], source_metadata["height"]))
    if profile is None:
        raise FlowImagePostprocessError(
            "FLOW_IMAGE_POSTPROCESS_UNSUPPORTED_GEOMETRY",
            f"{source_metadata['width']}x{source_metadata['height']}",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="flow-image-clean-", dir=output.parent) as temporary:
        work = Path(temporary)
        mask = work / "flow_mark_mask.png"
        candidate = work / ("candidate" + (output.suffix.lower() or ".png"))
        mask_sha256 = _write_mask(mask, profile)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-vf", f"removelogo=f={mask.name}",
            "-frames:v", "1", str(candidate),
        ]
        try:
            runner(command, cwd=str(work), capture_output=True, text=True, check=True)
            output_metadata = validate_image(candidate)
        except (subprocess.SubprocessError, OSError, AssetValidationError) as error:
            detail = getattr(error, "stderr", "") or str(error)
            raise FlowImagePostprocessError("FLOW_IMAGE_POSTPROCESS_FAILED", detail.strip()) from error
        if (output_metadata["width"], output_metadata["height"]) != (profile.width, profile.height):
            raise FlowImagePostprocessError("FLOW_IMAGE_POSTPROCESS_DIMENSIONS_CHANGED")
        os.replace(candidate, output)

    # Revalidate the final pathname after the atomic replacement.
    output_metadata = validate_image(output)
    return {
        "processor_name": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "profile_version": profile.version,
        "profile_sha256": _profile_fingerprint(profile),
        "mask_sha256": mask_sha256,
        "source_sha256": source_metadata["sha256"],
        "output_sha256": output_metadata["sha256"],
        "source_metadata": source_metadata,
        "output_metadata": output_metadata,
    }
