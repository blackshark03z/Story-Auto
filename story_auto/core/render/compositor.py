"""Provider-independent common scene compositor and narration/BGM mux."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .media import MediaError, MediaTarget, format_duration, run_command, validate_video


COMPOSER_VERSION = "story-auto-compositor/1.0.0"


def _filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _visual_filter(segments: list[dict[str, Any]]) -> tuple[str, str]:
    if len(segments) == 1:
        return "[0:v]setpts=PTS-STARTPTS[vout]", "[vout]"
    chains: list[str] = []
    current = "[0:v]"
    elapsed = float(segments[0]["target_duration"])
    # CUT boundaries are valid in mixed compositions; only apply xfade where
    # the frozen render plan explicitly requests a non-zero crossfade.
    for index in range(1, len(segments)):
        outgoing = segments[index - 1].get("transition", {})
        kind = outgoing.get("type", "CUT")
        if kind == "CUT":
            chains.append(f"{current}[{index}:v]setpts=PTS-STARTPTS[vx{index}]")
            current = f"[vx{index}]"
            elapsed += float(segments[index]["target_duration"])
            continue
        if kind != "CROSSFADE":
            raise MediaError("TRANSITION_POLICY_INVALID", "unsupported transition type")
        duration = float(outgoing.get("duration", 0))
        label = f"[vx{index}]"
        chains.append(f"{current}[{index}:v]xfade=transition=fade:duration={format_duration(duration)}:offset={format_duration(elapsed)}{label}")
        current = label
        elapsed += float(segments[index]["target_duration"])
    chains.append(f"{current}setpts=PTS-STARTPTS[vout]")
    return ";".join(chains), "[vout]"


def compose(
    *, clips: list[Path], segments: list[dict[str, Any]], narration: Path, output: Path,
    master_duration: float, subtitles_ass: Path | None = None, bgm: Path | None = None,
    bgm_volume: float = 0.12, target: MediaTarget = MediaTarget(), video_crf: int = 18,
) -> dict[str, Any]:
    if not clips or len(clips) != len(segments):
        raise MediaError("COMPOSITOR_INPUT_INVALID")
    inputs: list[str] = []
    for clip in clips:
        inputs.extend(["-i", str(clip)])
    narration_index = len(clips)
    inputs.extend(["-i", str(narration)])
    bgm_index = narration_index + 1
    if bgm:
        inputs.extend(["-stream_loop", "-1", "-i", str(bgm)])
    if len(clips) == 1:
        visual_filter, visual_label = _visual_filter(segments)
    elif any(item.get("transition", {}).get("type", "CUT") == "CUT" for item in segments[:-1]):
        # Mixed CUT/CROSSFADE plans are normalized to a deterministic concat
        # at the compositor boundary; this preserves exact segment timing and
        # avoids applying xfade across a hard-cut boundary.
        concat_inputs = "".join(f"[{index}:v]" for index in range(len(clips)))
        visual_filter, visual_label = f"{concat_inputs}concat=n={len(clips)}:v=1:a=0[vout]", "[vout]"
    else:
        visual_filter, visual_label = _visual_filter(segments)
    filters = [visual_filter]
    if subtitles_ass:
        filters.append(f"{visual_label}subtitles=filename='{_filter_path(subtitles_ass)}'[vsub]")
        visual_label = "[vsub]"
    if bgm:
        fade_out = max(0.0, master_duration - min(1.5, master_duration / 3))
        filters.extend([
            f"[{narration_index}:a]aresample=48000,volume=1.0[voice]",
            f"[{bgm_index}:a]aresample=48000,volume={bgm_volume},afade=t=in:st=0:d=1,"
            f"afade=t=out:st={format_duration(max(.001, fade_out))}:d={format_duration(min(1.5, master_duration / 3))}[music]",
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]",
        ])
        audio_label = "[aout]"
    else:
        filters.append(f"[{narration_index}:a]aresample=48000,alimiter=limit=0.95[aout]")
        audio_label = "[aout]"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters),
               "-map", visual_label, "-map", audio_label, "-t", format_duration(master_duration),
               "-c:v", "libx264", "-preset", "medium", "-crf", str(video_crf), "-pix_fmt", target.pixel_format,
               "-r", str(target.fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    run_command(command)
    return validate_video(output, target=target, silent=False, expected_duration=master_duration, tolerance=.12)
