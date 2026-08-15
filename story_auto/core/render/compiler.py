"""Compile heterogeneous sources into normalized silent MP4 scene clips."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from story_auto.core.visual import validate_ambient_presentation

from .media import MediaError, MediaTarget, format_duration, probe_media, run_command, validate_video


def _cover_filter(target: MediaTarget) -> str:
    return (f"scale={target.width}:{target.height}:force_original_aspect_ratio=increase,"
            f"crop={target.width}:{target.height},setsar=1,fps={target.fps},format={target.pixel_format}")


def _finishing_filter(profile: str) -> str:
    if profile == "NONE":
        return ""
    if profile != "NATURAL_SOFT":
        raise MediaError("RENDER_FINISHING_PROFILE_INVALID", profile)
    # Deliberately restrained: no blur and no sharpening. Source defects stay
    # visible to QC rather than being disguised during normalization.
    return "eq=saturation=0.94:contrast=0.97:gamma=0.99,noise=alls=1.2:allf=t+u"


def _ambient_filter(target: MediaTarget, duration: float, frames: int, presentation: dict[str, Any]) -> str:
    validate_ambient_presentation(presentation)
    motion = presentation["motion"]
    scale_change = float(presentation["total_scale_change"])
    translation = float(presentation["translation_fraction"])
    if motion == "STATIC":
        visual = _cover_filter(target)
    elif motion in {"SUBTLE_PUSH", "SUBTLE_PULL"}:
        denominator = max(1, frames - 1)
        if motion == "SUBTLE_PUSH":
            zoom = f"1+{scale_change:.5f}*on/{denominator}"
        else:
            zoom = f"1+{scale_change:.5f}*(1-on/{denominator})"
        visual = (_cover_filter(target).rsplit(",fps=", 1)[0] + ","
                  f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"d={frames}:s={target.width}x{target.height}:fps={target.fps},format={target.pixel_format}")
    else:
        pad = max(translation, 0.012 if motion == "MICRO_DRIFT" else translation)
        width, height = math.ceil(target.width * (1 + pad)), math.ceil(target.height * (1 + pad))
        prefix = (f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},")
        if motion == "SUBTLE_PAN_LEFT":
            x = f"(in_w-out_w)*(1-min(t/{format_duration(duration)},1))"
            y = "(in_h-out_h)/2"
        elif motion == "SUBTLE_PAN_RIGHT":
            x = f"(in_w-out_w)*min(t/{format_duration(duration)},1)"
            y = "(in_h-out_h)/2"
        else:
            x = f"(in_w-out_w)*(0.5+0.5*sin(2*PI*t/{format_duration(duration)}))"
            y = f"(in_h-out_h)*(0.5+0.5*sin(2*PI*t/{format_duration(duration)}+PI/2))"
        visual = prefix + f"crop={target.width}:{target.height}:x='{x}':y='{y}',setsar=1,fps={target.fps},format={target.pixel_format}"
    if presentation.get("overlay") == "FINE_GRAIN":
        visual += f",noise=alls={float(presentation['overlay_strength']):.2f}:allf=t+u:all_seed={int(presentation['seed']) % 100000}"
    return visual


def compile_image(source: Path, output: Path, *, duration: float, motion: str,
                  target: MediaTarget = MediaTarget(), finishing_profile: str = "NONE",
                  presentation: dict[str, Any] | None = None) -> dict:
    if motion not in {"STATIC", "SLOW_PUSH", "SLOW_PAN", "SUBTLE_PUSH", "SUBTLE_PULL",
                      "SUBTLE_PAN_LEFT", "SUBTLE_PAN_RIGHT", "MICRO_DRIFT"}:
        raise MediaError("IMAGE_MOTION_INVALID", motion)
    frames = max(1, round(duration * target.fps))
    if presentation is not None:
        validate_ambient_presentation(presentation)
        if motion != presentation["motion"]:
            raise MediaError("AMBIENT_PRESENTATION_MISMATCH")
        visual = _ambient_filter(target, duration, frames, presentation)
    elif motion == "STATIC":
        visual = _cover_filter(target)
    elif motion == "SLOW_PUSH":
        visual = (f"scale={target.width * 2}:{target.height * 2}:force_original_aspect_ratio=increase,"
                  f"crop={target.width * 2}:{target.height * 2},"
                  f"zoompan=z='min(zoom+0.00035,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"d={frames}:s={target.width}x{target.height}:fps={target.fps},format={target.pixel_format}")
    else:
        visual = (f"scale={math.ceil(target.width * 1.08)}:{math.ceil(target.height * 1.08)}:"
                  f"force_original_aspect_ratio=increase,crop={math.ceil(target.width * 1.08)}:{math.ceil(target.height * 1.08)},"
                  f"crop={target.width}:{target.height}:x='(in_w-out_w)*t/{format_duration(duration)}':"
                  f"y='(in_h-out_h)/2',setsar=1,fps={target.fps},format={target.pixel_format}")
    finish = _finishing_filter(finishing_profile)
    if finish: visual += "," + finish
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command(["ffmpeg", "-y", "-loop", "1", "-i", str(source), "-vf", visual,
                 "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", "-pix_fmt", target.pixel_format, "-color_range", "tv",
                 "-movflags", "+faststart", str(output)])
    return validate_video(output, target=target, silent=True, expected_duration=frames / target.fps)


def compile_video(source: Path, output: Path, *, duration: float, short_policy: str,
                  target: MediaTarget = MediaTarget(), finishing_profile: str = "NONE",
                  source_start: float = 0.0) -> dict:
    source_meta = probe_media(source)
    if source_start < 0 or source_start >= float(source_meta["duration_seconds"]):
        raise MediaError("USABLE_TEMPORAL_WINDOW_INVALID")
    shortage = duration - (float(source_meta["duration_seconds"]) - source_start)
    if shortage > .04 and short_policy != "FREEZE_TAIL":
        raise MediaError("RENDER_SOURCE_VIDEO_TOO_SHORT")
    filters = [_cover_filter(target)]
    if shortage > .04:
        filters.append(f"tpad=stop_mode=clone:stop_duration={format_duration(shortage)}")
    finish = _finishing_filter(finishing_profile)
    if finish: filters.append(finish)
    output.parent.mkdir(parents=True, exist_ok=True)
    seek = ["-ss", format_duration(source_start)] if source_start > 0 else []
    run_command(["ffmpeg", "-y", *seek, "-i", str(source), "-vf", ",".join(filters),
                 "-t", format_duration(duration), "-an", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", "-pix_fmt", target.pixel_format, "-r", str(target.fps),
                 "-movflags", "+faststart", str(output)])
    return validate_video(output, target=target, silent=True, expected_duration=duration)


def compile_hold(output: Path, *, duration: float, color: str = "black",
                 target: MediaTarget = MediaTarget()) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command(["ffmpeg", "-y", "-f", "lavfi", "-i",
                 f"color=c={color}:s={target.width}x{target.height}:r={target.fps}:d={format_duration(duration)}",
                 "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                 "-pix_fmt", target.pixel_format, "-movflags", "+faststart", str(output)])
    return validate_video(output, target=target, silent=True, expected_duration=duration)
