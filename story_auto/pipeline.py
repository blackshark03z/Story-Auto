"""The canonical Story Auto content, TTS, and alignment execution path."""

from __future__ import annotations

from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.audio import TTSRequest, TimedSpan, audio_duration_seconds, build_alignment, validate_alignment
from story_auto.core.checkpoint import CheckpointStore, fingerprint
from story_auto.core.content import ContentValidationError, narration_hash, parse_content_markdown
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.providers.tts import provider_for
from story_auto.core.planning import run_planning_stages

CONTENT_PRODUCER_VERSION = "story-auto-content-stage/1.0.0"
CONTENT_MANIFEST_SCHEMA_VERSION = "story-auto-content-manifest/1.0.0"
TTS_PRODUCER_VERSION = "story-auto-tts-stage/1.0.0"
ALIGNMENT_PRODUCER_VERSION = "story-auto-alignment-stage/1.0.0"


def _tts_settings(config) -> tuple[str, str, dict]:
    tts = config.settings.get("tts")
    if not isinstance(tts, dict): raise ValueError("project settings.tts is required to run audio")
    provider = tts.get("provider")
    if provider not in {"elevenlabs", "typecast"}: raise ValueError("tts.provider must be elevenlabs or typecast")
    if tts.get("allow_cross_provider_fallback", False) is not False: raise ValueError("cross-provider fallback is not supported")
    specific = tts.get(provider)
    if not isinstance(specific, dict) or not isinstance(specific.get("voice_id"), str) or not specific["voice_id"].strip():
        raise ValueError(f"tts.{provider}.voice_id is required")
    return provider, specific["voice_id"], specific


def _spans_for_result(adapter, request: TTSRequest, result) -> list[TimedSpan]:
    return [TimedSpan(**item) for item in adapter.align(request, result)]


def run_audio_stages(runtime_root: Path | str, project_id: str, *, adapter=None) -> tuple[str, str]:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    source = paths.content_file.read_text(encoding="utf-8")
    narration = parse_content_markdown(source).narration
    narration_sha256 = narration_hash(narration)
    provider_name, voice_id, settings = _tts_settings(config)
    extension = "wav" if provider_name == "typecast" else "mp3"
    audio_relative, manifest_relative, alignment_relative = f"output/voice.{extension}", "output/audio_manifest.json", "output/alignment.json"
    tts_fingerprint = fingerprint(stage_name="tts", producer_version=TTS_PRODUCER_VERSION, artifact_schema_version="story-auto-audio/1.0.0", direct_inputs={"narration_sha256": narration_sha256, "provider": provider_name, "voice_id": voice_id}, settings=settings)
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths)
        audio_path, manifest_path = paths.artifact_path(audio_relative), paths.artifact_path(manifest_relative)
        decision = checkpoints.decide("tts", tts_fingerprint)
        valid_audio = False
        if decision.action == "SKIP":
            try:
                manifest = read_json(manifest_path); valid_audio = audio_path.stat().st_size > 0 and manifest["audio_sha256"] == sha256_file(audio_path) and manifest["narration_sha256"] == narration_sha256
            except Exception: valid_audio = False
        active_adapter = adapter or provider_for(provider_name)
        request = TTSRequest(narration, narration_sha256, provider_name, voice_id, settings)
        if decision.action == "SKIP" and valid_audio:
            tts_action, result = "SKIP", None
            manifest = read_json(manifest_path)
        else:
            try:
                result = active_adapter.generate(request, audio_path)
                if not audio_path.is_file() or audio_path.stat().st_size == 0: raise RuntimeError("provider did not publish audio")
                validated_duration = audio_duration_seconds(audio_path, provider=provider_name)
                audio_sha256 = sha256_file(audio_path)
                manifest = {"schema_version":"story-auto-audio/1.0.0", "audio_path":audio_relative, "audio_sha256":audio_sha256, "duration_seconds":validated_duration, "provider":provider_name, "voice_id":voice_id, "narration_sha256":narration_sha256, "alignment_method":result.alignment_method, "metadata":result.metadata}
                atomic_write_json(manifest_path, manifest)
                checkpoints.record("tts", fingerprint=tts_fingerprint, status="SUCCESS", outputs=[audio_relative, manifest_relative], producer_version=TTS_PRODUCER_VERSION); tts_action="RUN"
            except Exception:
                checkpoints.record("tts", fingerprint=tts_fingerprint, status="FAILED", outputs=[], producer_version=TTS_PRODUCER_VERSION); raise
        alignment_fingerprint = fingerprint(stage_name="alignment", producer_version=ALIGNMENT_PRODUCER_VERSION, artifact_schema_version="story-auto-alignment/1.0.0", direct_inputs={"audio_sha256":manifest["audio_sha256"], "narration_sha256":narration_sha256, "method":manifest["alignment_method"]}, settings={})
        alignment_path = paths.artifact_path(alignment_relative)
        alignment_decision = checkpoints.decide("alignment", alignment_fingerprint)
        if tts_action == "SKIP" and alignment_decision.action == "SKIP":
            try: validate_alignment(read_json(alignment_path), narration=narration, narration_sha256=narration_sha256, audio_sha256=manifest["audio_sha256"], duration_seconds=float(manifest["duration_seconds"])); return tts_action, "SKIP"
            except Exception: pass
        try:
            if result is None:
                from story_auto.core.audio.contracts import TTSResult
                result = TTSResult(audio_path, provider_name, voice_id, float(manifest["duration_seconds"]), narration_sha256, manifest["metadata"], manifest["alignment_method"])
            spans = _spans_for_result(active_adapter, request, result)
            duration = float(manifest["duration_seconds"])
            if duration <= 0: duration = max(span.end for span in spans)
            alignment = build_alignment(project_id=project_id, audio_path=audio_relative, audio_sha256=manifest["audio_sha256"], narration_sha256=narration_sha256, duration_seconds=duration, source=manifest["alignment_method"], spans=spans)
            validate_alignment(alignment, narration=narration, narration_sha256=narration_sha256, audio_sha256=manifest["audio_sha256"], duration_seconds=duration)
            atomic_write_json(alignment_path, alignment); checkpoints.record("alignment", fingerprint=alignment_fingerprint, status="SUCCESS", outputs=[alignment_relative], producer_version=ALIGNMENT_PRODUCER_VERSION)
        except Exception:
            checkpoints.record("alignment", fingerprint=alignment_fingerprint, status="FAILED", outputs=[], producer_version=ALIGNMENT_PRODUCER_VERSION); raise
    return tts_action, "RUN"


def run_content_stage(runtime_root: Path | str, project_id: str) -> str:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    if not paths.content_file.is_file():
        raise ContentValidationError(f"missing content.md: {paths.content_file}")
    try:
        source = paths.content_file.read_text(encoding="utf-8")
    except OSError as error:
        raise ContentValidationError(f"could not read content.md: {paths.content_file}") from error
    narration = parse_content_markdown(source).narration
    narration_sha256 = narration_hash(narration)
    stage_fingerprint = fingerprint(stage_name="content", producer_version=CONTENT_PRODUCER_VERSION,
                                    artifact_schema_version=CONTENT_MANIFEST_SCHEMA_VERSION,
                                    direct_inputs={"narration_sha256": narration_sha256}, settings={})
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths)
        decision = checkpoints.decide("content", stage_fingerprint)
        if decision.action == "SKIP":
            return "SKIP"
        output = "output/content_manifest.json"
        try:
            atomic_write_json(paths.artifact_path(output), {
                "schema_version": CONTENT_MANIFEST_SCHEMA_VERSION, "narration_sha256": narration_sha256,
                "character_count": len(narration), "paragraph_count": len(narration.split("\n\n")),
            })
            checkpoints.record("content", fingerprint=stage_fingerprint, status="SUCCESS", outputs=[output], producer_version=CONTENT_PRODUCER_VERSION)
        except Exception:
            checkpoints.record("content", fingerprint=stage_fingerprint, status="FAILED", outputs=[], producer_version=CONTENT_PRODUCER_VERSION)
            raise
    return "RUN"
