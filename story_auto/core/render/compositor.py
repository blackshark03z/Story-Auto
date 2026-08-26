"""Provider-independent common scene compositor and narration/BGM mux."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .media import MediaError, MediaTarget, format_duration, run_command, validate_video
from .waveform import visualizer_spec


COMPOSER_VERSION = "story-auto-compositor/1.2.0"


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
    audio_visualizer: bool | dict[str, object] = False,
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
    visualizer = (dict(audio_visualizer) if isinstance(audio_visualizer, dict)
                  else visualizer_spec(enabled=bool(audio_visualizer), target_width=target.width, target_height=target.height))
    if visualizer.get("enabled"):
        # showwaves consumes the canonical narration stream directly. It is
        # deterministic, stays frame-synchronous with speech, and never adds
        # another audio source or provider dependency.
        size = visualizer.get("size")
        position = visualizer.get("position_pixels")
        if (not isinstance(size, list) or len(size) != 2 or not isinstance(position, list) or len(position) != 2
                or any(not isinstance(value, int) for value in [*size, *position])):
            raise MediaError("WAVEFORM_GEOMETRY_INVALID")
        wave_width, wave_height = size
        wave_x, wave_y = position
        if wave_width <= 0 or wave_height <= 0 or wave_x < 0 or wave_y < 0 or wave_x + wave_width > target.width or wave_y + wave_height > target.height:
            raise MediaError("WAVEFORM_GEOMETRY_INVALID")
        gain = visualizer.get("amplitude_gain")
        scale = visualizer.get("amplitude_scale")
        color = visualizer.get("color")
        if (not isinstance(gain, (int, float)) or isinstance(gain, bool) or not 0 < gain <= 8
                or scale not in {"lin", "sqrt", "cbrt", "4thrt", "5thrt", "log"}
                or not isinstance(color, str) or not color):
            raise MediaError("WAVEFORM_STYLE_INVALID")
        filters.append(f"[{narration_index}:a]asplit=2[voice_source][wave_source]")
        filters.append(f"[wave_source]volume={float(gain):.3f},showwaves=s={wave_width}x{wave_height}:mode=cline:scale={scale}:colors={color},format=rgba[wave]")
        filters.append(f"{visual_label}[wave]overlay=x={wave_x}:y={wave_y}:format=auto[vwave]")
        visual_label = "[vwave]"
        narration_audio = "[voice_source]"
    else:
        narration_audio = f"[{narration_index}:a]"
    if bgm:
        fade_out = max(0.0, master_duration - min(1.5, master_duration / 3))
        filters.extend([
            f"{narration_audio}aresample=48000,volume=1.0[voice]",
            f"[{bgm_index}:a]aresample=48000,volume={bgm_volume},afade=t=in:st=0:d=1,"
            f"afade=t=out:st={format_duration(max(.001, fade_out))}:d={format_duration(min(1.5, master_duration / 3))}[music]",
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]",
        ])
        audio_label = "[aout]"
    else:
        filters.append(f"{narration_audio}aresample=48000,alimiter=limit=0.95[aout]")
        audio_label = "[aout]"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters),
               "-map", visual_label, "-map", audio_label, "-t", format_duration(master_duration),
               "-c:v", "libx264", "-preset", "medium", "-crf", str(video_crf), "-pix_fmt", target.pixel_format,
               "-r", str(target.fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    run_command(command)
    return validate_video(output, target=target, silent=False, expected_duration=master_duration, tolerance=.12)
