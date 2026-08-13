"""Compile heterogeneous sources into normalized silent MP4 scene clips."""

from __future__ import annotations

import math
from pathlib import Path

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


def compile_image(source: Path, output: Path, *, duration: float, motion: str,
                  target: MediaTarget = MediaTarget(), finishing_profile: str = "NONE") -> dict:
    if motion not in {"STATIC", "SLOW_PUSH", "SLOW_PAN"}:
        raise MediaError("IMAGE_MOTION_INVALID", motion)
    frames = max(1, round(duration * target.fps))
    if motion == "STATIC":
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
                  target: MediaTarget = MediaTarget(), finishing_profile: str = "NONE") -> dict:
    source_meta = probe_media(source)
    shortage = duration - float(source_meta["duration_seconds"])
    if shortage > .04 and short_policy != "FREEZE_TAIL":
        raise MediaError("RENDER_SOURCE_VIDEO_TOO_SHORT")
    filters = [_cover_filter(target)]
    if shortage > .04:
        filters.append(f"tpad=stop_mode=clone:stop_duration={format_duration(shortage)}")
    finish = _finishing_filter(finishing_profile)
    if finish: filters.append(finish)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command(["ffmpeg", "-y", "-i", str(source), "-vf", ",".join(filters),
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
