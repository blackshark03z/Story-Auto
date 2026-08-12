"""Local asset validation before a provider result can become selected."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
from story_auto.core.artifacts import sha256_file


class AssetValidationError(RuntimeError):
    def __init__(self, failure_class: str): self.failure_class = failure_class; super().__init__(failure_class)


def validate_image(path: Path) -> dict:
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size; fmt = image.format
        if width < 16 or height < 16: raise ValueError()
        return {"width": width, "height": height, "format": fmt, "sha256": sha256_file(path)}
    except Exception as error: raise AssetValidationError("IMAGE_ASSET_INVALID") from error


def validate_video(path: Path, *, runner=subprocess.run) -> dict:
    try:
        result = runner(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
        value = json.loads(result.stdout); streams = value["streams"]; video = next(s for s in streams if s.get("codec_type") == "video")
        duration = float(video.get("duration") or value.get("format", {}).get("duration") or 0)
        if duration <= 0 or int(video.get("width", 0)) <= 0 or int(video.get("height", 0)) <= 0: raise ValueError()
        return {"duration_seconds": duration, "width": int(video["width"]), "height": int(video["height"]), "codec": video.get("codec_name"), "container": value.get("format", {}).get("format_name"), "audio_present": any(s.get("codec_type") == "audio" for s in streams), "sha256": sha256_file(path)}
    except Exception as error: raise AssetValidationError("VIDEO_ASSET_INVALID") from error
