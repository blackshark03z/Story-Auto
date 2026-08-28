"""The canonical Story Auto content, TTS, and alignment execution path."""

from __future__ import annotations

from pathlib import Path

import shutil

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.audio import TTSRequest, TimedSpan, audio_duration_seconds, build_alignment, deterministic_text_alignment, parse_srt_file, validate_alignment
from story_auto.core.audio.media import inspect_audio
from story_auto.core.checkpoint import CheckpointStore, fingerprint
from story_auto.core.content import ContentValidationError, narration_hash, parse_content_markdown
from story_auto.core.project import RuntimeLayout, execution_mode, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.providers.tts import provider_for
from story_auto.core.planning import run_planning_stages

CONTENT_PRODUCER_VERSION = "story-auto-content-stage/1.0.0"
CONTENT_MANIFEST_SCHEMA_VERSION = "story-auto-content-manifest/1.0.0"
TTS_PRODUCER_VERSION = "story-auto-tts-stage/1.1.0"
ALIGNMENT_PRODUCER_VERSION = "story-auto-alignment-stage/1.0.0"
SRT_TIMELINE_TOLERANCE_SECONDS = 0.5


def _tts_settings(config) -> tuple[str, str, dict]:
    tts = config.settings.get("tts")
    if not isinstance(tts, dict): raise ValueError("project settings.tts is required to run audio")
    provider = tts.get("provider")
    if provider not in {"elevenlabs", "typecast", "kokoro_local"}: raise ValueError("tts.provider must be elevenlabs, typecast, or kokoro_local")
    if tts.get("allow_cross_provider_fallback", False) is not False: raise ValueError("cross-provider fallback is not supported")
    specific = tts.get(provider)
    if not isinstance(specific, dict) or not isinstance(specific.get("voice_id"), str) or not specific["voice_id"].strip():
        raise ValueError(f"tts.{provider}.voice_id is required")
    return provider, specific["voice_id"], specific


def _spans_for_result(adapter, request: TTSRequest, result) -> list[TimedSpan]:
    return [TimedSpan(**item) for item in adapter.align(request, result)]


def _valid_reusable_audio(paths, narration_sha256: str) -> tuple[dict, Path] | None:
    """Do not trust a saved path alone: verify manifest identity and observed media again."""
    try:
        manifest = read_json(paths.artifact_path("output/audio_manifest.json"))
        relative = manifest["audio_path"]
        audio_path = paths.artifact_path(relative)
        if manifest.get("narration_sha256") != narration_sha256 or manifest.get("audio_sha256") != sha256_file(audio_path):
            return None
        observed = inspect_audio(audio_path, provider="existing_audio")
        if abs(float(manifest.get("duration_seconds", 0)) - float(observed["duration_seconds"])) > .15:
            return None
        return manifest, audio_path
    except Exception:
        return None


def adopt_existing_audio(runtime_root: Path | str, project_id: str, source: Path | str, *, source_type: str = "IMPORTED") -> dict:
    """Copy, validate, hash, and align operator-supplied narration inside its project boundary."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    source_path = Path(source)
    if source_type not in {"IMPORTED", "REUSED"} or not source_path.is_file():
        raise ValueError("NARRATION_AUDIO_SOURCE_INVALID")
    source_metadata = inspect_audio(source_path, provider="existing_audio")
    source_sha = sha256_file(source_path)
    suffix = source_path.suffix.lower()
    target_relative = f"output/voice_existing{suffix}"
    target = paths.artifact_path(target_relative)
    with ProjectLock(paths.runtime, project_id):
        temporary = target.with_name(target.stem + ".partial" + target.suffix)
        try:
            shutil.copyfile(source_path, temporary)
            observed = inspect_audio(temporary, provider="existing_audio")
            if sha256_file(temporary) != source_sha:
                raise ValueError("NARRATION_AUDIO_COPY_IDENTITY_MISMATCH")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        narration = parse_content_markdown(paths.content_file.read_text(encoding="utf-8")).narration
        narration_sha = narration_hash(narration)
        manifest = {
            "schema_version": "story-auto-audio/1.0.0", "audio_path": target_relative,
            "audio_sha256": source_sha, "duration_seconds": observed["duration_seconds"],
            "provider": "existing_audio", "voice_id": None, "narration_sha256": narration_sha,
            "alignment_method": "deterministic_text_proportional_no_asr", "source_type": source_type,
            "canonical_path": target_relative, "media_metadata": observed,
            "provenance": {"imported_filename": source_path.name, "source_sha256": source_sha,
                           "validation": "READABLE_AUDIO_STREAM"}, "metadata": {},
        }
        atomic_write_json(paths.artifact_path("output/audio_manifest.json"), manifest)
        alignment = deterministic_text_alignment(project_id=project_id, audio_path=target_relative,
            audio_sha256=source_sha, narration_sha256=narration_sha, narration=narration,
            duration_seconds=float(observed["duration_seconds"]))
        validate_alignment(alignment, narration=narration, narration_sha256=narration_sha,
                           audio_sha256=source_sha, duration_seconds=float(observed["duration_seconds"]))
        atomic_write_json(paths.artifact_path("output/alignment.json"), alignment)
    return manifest


def adopt_existing_srt(runtime_root: Path | str, project_id: str, source: Path | str, *, source_type: str = "IMPORTED") -> dict:
    """Copy and normalize SRT into the project, then bind it as canonical timing."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    source_path = Path(source)
    if source_type not in {"IMPORTED", "REUSED"} or not source_path.is_file() or source_path.suffix.lower() != ".srt":
        raise ValueError("SRT_SOURCE_INVALID")
    narration = parse_content_markdown(paths.content_file.read_text(encoding="utf-8")).narration
    narration_sha = narration_hash(narration)
    reusable = _valid_reusable_audio(paths, narration_sha)
    if reusable is None:
        raise ValueError("SRT_REQUIRES_VALID_NARRATION_AUDIO")
    audio_manifest, _ = reusable
    target_relative = "output/timing.srt"
    target = paths.artifact_path(target_relative)
    with ProjectLock(paths.runtime, project_id):
        temporary = target.with_name("timing.partial.srt")
        try:
            shutil.copyfile(source_path, temporary)
            cues, encoding, stats = parse_srt_file(temporary)
            source_sha = sha256_file(temporary)
            difference = abs(float(audio_manifest["duration_seconds"]) - float(stats["last_timestamp"]))
            if difference > SRT_TIMELINE_TOLERANCE_SECONDS:
                raise ValueError("AUDIO_SRT_DURATION_MISMATCH")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        manifest = {"schema_version": "story-auto-srt/1.0.0", "source_type": source_type,
            "canonical_path": target_relative, "sha256": source_sha, "encoding": encoding,
            "cue_count": stats["raw_cue_count"], "non_empty_cue_count": stats["text_cue_count"],
            "first_timestamp": stats["first_timestamp"], "last_timestamp": stats["last_timestamp"],
            "normalization": {"RAW_CUE_COUNT": stats["raw_cue_count"], "TEXT_CUE_COUNT": stats["text_cue_count"],
                              "IGNORED_EMPTY_CUES": stats["ignored_empty_cues"]}, "validation_result": "PASS",
            "timeline_match": {"status": "PASS", "audio_duration": audio_manifest["duration_seconds"],
                               "srt_end_time": stats["last_timestamp"], "tolerance_seconds": SRT_TIMELINE_TOLERANCE_SECONDS}}
        atomic_write_json(paths.artifact_path("output/srt_manifest.json"), manifest)
        alignment = build_alignment(project_id=project_id, audio_path=audio_manifest["audio_path"], audio_sha256=audio_manifest["audio_sha256"],
            narration_sha256=narration_sha, duration_seconds=float(audio_manifest["duration_seconds"]), source="SRT",
            spans=[TimedSpan(cue.text, cue.start, cue.end) for cue in cues])
        alignment["timing_source"] = "SRT"
        alignment["segments"] = [{"segment_id": cue.cue_id, "start": round(cue.start, 6), "end": round(cue.end, 6), "text": cue.text,
                                  "canonical_cue_id": cue.cue_id} for cue in cues]
        validate_alignment(alignment, narration=narration, narration_sha256=narration_sha,
                           audio_sha256=audio_manifest["audio_sha256"], duration_seconds=float(audio_manifest["duration_seconds"]))
        atomic_write_json(paths.artifact_path("output/alignment.json"), alignment)
    return manifest


def run_audio_stages(runtime_root: Path | str, project_id: str, *, adapter=None) -> tuple[str, str]:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    source = paths.content_file.read_text(encoding="utf-8")
    narration = parse_content_markdown(source).narration
    narration_sha256 = narration_hash(narration)
    mode = execution_mode(config.settings)
    if mode in {"EXISTING_VOICE", "VISUALS_ONLY", "RENDER_ONLY"}:
        reusable = _valid_reusable_audio(paths, narration_sha256)
        if reusable is None:
            raise ValueError("No narration audio has been selected.")
        manifest, _ = reusable
        alignment_path = paths.artifact_path("output/alignment.json")
        srt_manifest_path = paths.artifact_path("output/srt_manifest.json")
        if srt_manifest_path.is_file():
            srt_manifest = read_json(srt_manifest_path)
            if srt_manifest.get("validation_result") != "PASS" or srt_manifest.get("timeline_match", {}).get("status") != "PASS":
                raise ValueError("SRT_VALIDATION_REQUIRED")
        try:
            alignment = read_json(alignment_path)
            validate_alignment(alignment, narration=narration, narration_sha256=narration_sha256,
                               audio_sha256=manifest["audio_sha256"], duration_seconds=float(manifest["duration_seconds"]))
            return "REUSE", "REUSE"
        except Exception:
            if srt_manifest_path.is_file():
                raise ValueError("SRT_CANONICAL_ALIGNMENT_INVALID")
            alignment = deterministic_text_alignment(project_id=project_id, audio_path=manifest["audio_path"],
                audio_sha256=manifest["audio_sha256"], narration_sha256=narration_sha256, narration=narration,
                duration_seconds=float(manifest["duration_seconds"]))
            atomic_write_json(alignment_path, alignment)
            return "REUSE", "RUN"
    provider_name, voice_id, settings = _tts_settings(config)
    extension = "wav" if provider_name in {"typecast", "kokoro_local"} else "mp3"
    audio_relative, manifest_relative, alignment_relative = f"output/voice.{extension}", "output/audio_manifest.json", "output/alignment.json"
    active_adapter = adapter or provider_for(provider_name)
    provider_identity = active_adapter.fingerprint_settings(settings) if hasattr(active_adapter, "fingerprint_settings") else {}
    tts_fingerprint = fingerprint(stage_name="tts", producer_version=TTS_PRODUCER_VERSION, artifact_schema_version="story-auto-audio/1.0.0", direct_inputs={"narration_sha256": narration_sha256, "provider": provider_name, "voice_id": voice_id}, settings={"provider_settings":settings,"provider_identity":provider_identity})
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths)
        audio_path, manifest_path = paths.artifact_path(audio_relative), paths.artifact_path(manifest_relative)
        decision = checkpoints.decide("tts", tts_fingerprint)
        valid_audio = False
        if decision.action == "SKIP":
            try:
                manifest = read_json(manifest_path); valid_audio = audio_path.stat().st_size > 0 and manifest["audio_sha256"] == sha256_file(audio_path) and manifest["narration_sha256"] == narration_sha256
            except Exception: valid_audio = False
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
