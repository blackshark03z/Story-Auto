"""Small official Gemini media client with safe acquisition and resumable Veo jobs.

The client consumes provider-independent prompts and local reference files. API
shapes, key rotation, signed result URLs, and operation polling stay isolated
inside this module. No credential or result URL is returned in provenance.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import mimetypes
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterable
import urllib.error
import urllib.request

from story_auto.core.resources import ensure_free_space
from story_auto.providers.credentials import provider_keys
from story_auto.providers.flow.validation import validate_image, validate_video


API_BASE = "https://generativelanguage.googleapis.com/v1beta"
IMAGE_MODELS = ("gemini-3.1-flash-image", "gemini-3-pro-image")
VIDEO_MODELS = ("gemini-omni-flash-preview", "veo-3.1-generate-preview")


class GeminiMediaError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "", *, dispatch_confirmed: bool = False) -> None:
        self.failure_class = failure_class
        self.detail = detail
        self.dispatch_confirmed = dispatch_confirmed
        super().__init__(failure_class + (f": {detail}" if detail else ""))


@dataclass(frozen=True)
class ModelCapability:
    model: str
    display_name: str
    methods: tuple[str, ...]
    media_type: str
    reference_mode: str


@dataclass(frozen=True)
class MediaResult:
    path: Path
    provider: str
    model: str
    endpoint_identity: str
    request_id: str | None
    operation_id: str | None
    reference_mode: str
    output_count: int
    metadata: dict[str, Any]


Transport = Callable[[str, str, dict[str, Any] | None, str, float], tuple[dict[str, Any], int]]
BinaryTransport = Callable[[str, str, float], bytes]


def _classify_http(status: int, provider_status: str = "") -> str:
    if provider_status in {"API_KEY_INVALID", "UNAUTHENTICATED", "PERMISSION_DENIED"}:
        return "CREDENTIAL_OR_ACCESS_DENIED"
    if status in {401, 403}:
        return "CREDENTIAL_OR_ACCESS_DENIED"
    if status == 429:
        return "RATE_LIMITED"
    if status in {408, 409, 425} or status >= 500:
        return "PROVIDER_TRANSIENT"
    if status == 400:
        return "CAPABILITY_OR_REQUEST_INVALID"
    return "PROVIDER_GENERATION_FAILED"


def _mime(path: Path) -> str:
    value = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not value.startswith("image/"):
        raise GeminiMediaError("REFERENCE_ASSET_INVALID", path.suffix)
    return value


def _inline_image(path: Path) -> dict[str, str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise GeminiMediaError("REFERENCE_ASSET_INVALID")
    validate_image(path)
    return {"mime_type": _mime(path), "data": base64.b64encode(path.read_bytes()).decode("ascii")}


def _default_transport(url: str, method: str, body: dict[str, Any] | None, key: str,
                       timeout: float) -> tuple[dict[str, Any], int]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), int(response.status)
    except urllib.error.HTTPError as error:
        detail = ""
        provider_status = ""
        try:
            payload = json.loads(error.read().decode("utf-8"))
            if isinstance(payload, list) and payload:
                payload = payload[0]
            provider_error = payload.get("error", {})
            provider_status = str(provider_error.get("status") or provider_error.get("code") or "")
            detail = str(provider_error.get("message") or provider_status)[:240]
        except Exception:
            pass
        failure = _classify_http(error.code, provider_status)
        if "API key not valid" in detail or "invalid authentication credentials" in detail:
            failure = "CREDENTIAL_OR_ACCESS_DENIED"
        if method == "POST" and failure == "PROVIDER_TRANSIENT":
            failure = "AMBIGUOUS_POST_DISPATCH"
        raise GeminiMediaError(failure, detail, dispatch_confirmed=method == "POST") from error
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise GeminiMediaError("AMBIGUOUS_POST_DISPATCH" if method == "POST" else "PROVIDER_TRANSIENT",
                               type(error).__name__, dispatch_confirmed=method == "POST") from error


def _default_binary(url: str, key: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise GeminiMediaError(_classify_http(error.code), dispatch_confirmed=True) from error
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise GeminiMediaError("ASSET_ACQUISITION_FAILED", type(error).__name__, dispatch_confirmed=True) from error


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _extract_base64(payload: dict[str, Any], *, kind: str) -> bytes:
    direct = payload.get(f"output_{kind}")
    if isinstance(direct, dict) and isinstance(direct.get("data"), str):
        return base64.b64decode(direct["data"], validate=True)
    prefixes = ("image/",) if kind == "image" else ("video/",)
    for node in _walk(payload):
        mime = str(node.get("mime_type") or node.get("mimeType") or "")
        data = node.get("data") or node.get("bytesBase64Encoded")
        if mime.startswith(prefixes) and isinstance(data, str):
            return base64.b64decode(data, validate=True)
    raise GeminiMediaError("PROVIDER_RESULT_MISSING", kind, dispatch_confirmed=True)


def _safe_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("id") or payload.get("name")
    if not isinstance(value, str):
        return None
    return value.rsplit("/", 1)[-1][:160]


class GeminiMediaClient:
    provider = "google_gemini_api"

    def __init__(self, *, transport: Transport = _default_transport,
                 binary_transport: BinaryTransport = _default_binary,
                 keys: list[str] | None = None, timeout: float = 180.0,
                 poll_interval: float = 10.0, max_poll_seconds: float = 900.0) -> None:
        self.transport = transport
        self.binary_transport = binary_transport
        self.keys = list(keys if keys is not None else provider_keys("gemini"))
        if not self.keys:
            raise GeminiMediaError("CREDENTIAL_MISSING")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll_seconds = max_poll_seconds
        self._key_index = 0

    @property
    def _key(self) -> str:
        return self.keys[self._key_index]

    def _request(self, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
        last: GeminiMediaError | None = None
        start = self._key_index
        for offset in range(len(self.keys)):
            self._key_index = (start + offset) % len(self.keys)
            try:
                payload, _ = self.transport(API_BASE + "/" + path.lstrip("/"), method, body, self._key, self.timeout)
                return payload
            except GeminiMediaError as error:
                last = error
                retryable = {"CREDENTIAL_OR_ACCESS_DENIED", "RATE_LIMITED"}
                if method != "POST":
                    retryable.add("PROVIDER_TRANSIENT")
                if error.failure_class not in retryable:
                    raise
        assert last is not None
        raise last

    def discover_models(self) -> list[ModelCapability]:
        payload = self._request("models")
        found: list[ModelCapability] = []
        for item in payload.get("models", []):
            model = str(item.get("name", "")).rsplit("/", 1)[-1]
            if model in IMAGE_MODELS:
                found.append(ModelCapability(model, str(item.get("displayName", model)),
                                             tuple(item.get("supportedGenerationMethods", [])), "IMAGE", "MULTI_REFERENCE"))
            elif model == "gemini-omni-flash-preview":
                found.append(ModelCapability(model, str(item.get("displayName", model)),
                                             tuple(item.get("supportedGenerationMethods", [])), "VIDEO", "IMAGE_AND_SUBJECT_REFERENCE"))
            elif model == "veo-3.1-generate-preview":
                found.append(ModelCapability(model, str(item.get("displayName", model)),
                                             tuple(item.get("supportedGenerationMethods", [])), "VIDEO", "FIRST_FRAME_AND_UP_TO_3_REFERENCES"))
        return found

    def generate_image(self, *, model: str, prompt: str, references: list[Path], destination: Path,
                       aspect_ratio: str = "16:9", image_size: str = "2K") -> MediaResult:
        if model not in IMAGE_MODELS:
            raise GeminiMediaError("MODEL_NOT_IMAGE_CAPABLE", model)
        inputs: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        inputs.extend({"type": "image", **_inline_image(path)} for path in references)
        payload = self._request("interactions", method="POST", body={
            "model": model,
            "input": inputs,
            "response_format": {"type": "image", "aspect_ratio": aspect_ratio, "image_size": image_size},
        })
        data = _extract_base64(payload, kind="image")
        ensure_free_space(destination.parent, minimum_free_bytes=max(64 * 1024 * 1024, len(data) * 2))
        candidate = destination.with_suffix(destination.suffix + ".candidate")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(data)
        metadata = validate_image(candidate)
        os.replace(candidate, destination)
        metadata = validate_image(destination)
        return MediaResult(destination, self.provider, model, "interactions", _safe_id(payload), None,
                           "MULTI_REFERENCE" if references else "TEXT_TO_IMAGE", 1, metadata)

    def generate_omni_video(self, *, prompt: str, references: list[Path], destination: Path,
                            task: str, aspect_ratio: str = "16:9") -> MediaResult:
        if task not in {"image_to_video", "reference_to_video"} or not references:
            raise GeminiMediaError("REFERENCE_MODE_INVALID")
        inputs: list[dict[str, Any]] = [{"type": "image", **_inline_image(path)} for path in references]
        inputs.append({"type": "text", "text": prompt})
        payload = self._request("interactions", method="POST", body={
            "model": "gemini-omni-flash-preview",
            "input": inputs,
            "response_format": {"type": "video", "aspect_ratio": aspect_ratio},
            "generation_config": {"video_config": {"task": task}},
        })
        data = _extract_base64(payload, kind="video")
        ensure_free_space(destination.parent, minimum_free_bytes=max(64 * 1024 * 1024, len(data) * 2))
        candidate = destination.with_suffix(destination.suffix + ".candidate")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(data)
        metadata = validate_video(candidate)
        os.replace(candidate, destination)
        metadata = validate_video(destination)
        return MediaResult(destination, self.provider, "gemini-omni-flash-preview", "interactions",
                           _safe_id(payload), None, task.upper(), 1, metadata)

    def submit_veo(self, *, prompt: str, references: list[Path], mode: str,
                   aspect_ratio: str = "16:9", duration_seconds: int = 8,
                   resolution: str = "720p") -> str:
        if not references or mode not in {"FIRST_FRAME", "REFERENCE_IMAGES"}:
            raise GeminiMediaError("REFERENCE_MODE_INVALID")
        instance: dict[str, Any] = {"prompt": prompt}
        images = [_inline_image(path) for path in references]
        # predictLongRunning currently uses the media prediction wire shape,
        # even though generateContent examples describe inlineData.
        def veo_image(item: dict[str, str]) -> dict[str, str]:
            return {"bytesBase64Encoded": item["data"], "mimeType": item["mime_type"]}
        if mode == "FIRST_FRAME":
            instance["image"] = veo_image(images[0])
        else:
            instance["referenceImages"] = [
                {"image": veo_image(item), "referenceType": "asset"}
                for item in images[:3]
            ]
        payload = self._request("models/veo-3.1-generate-preview:predictLongRunning", method="POST", body={
            "instances": [instance],
            "parameters": {"aspectRatio": aspect_ratio, "durationSeconds": duration_seconds,
                           "resolution": resolution, "sampleCount": 1},
        })
        name = payload.get("name")
        if not isinstance(name, str) or not name.startswith("operations/"):
            raise GeminiMediaError("PROVIDER_JOB_ID_MISSING", dispatch_confirmed=True)
        return name

    def complete_veo(self, *, operation_name: str, destination: Path,
                     on_poll: Callable[[str], None] | None = None) -> MediaResult:
        if not operation_name.startswith("operations/"):
            raise GeminiMediaError("PROVIDER_JOB_ID_INVALID")
        deadline = time.monotonic() + self.max_poll_seconds
        payload: dict[str, Any]
        while True:
            payload = self._request(operation_name)
            if payload.get("done") is True:
                break
            if on_poll:
                on_poll(operation_name)
            if time.monotonic() >= deadline:
                raise GeminiMediaError("PROVIDER_JOB_PENDING", operation_name.rsplit("/", 1)[-1], dispatch_confirmed=True)
            time.sleep(self.poll_interval)
        if isinstance(payload.get("error"), dict):
            status = str(payload["error"].get("status") or "PROVIDER_GENERATION_FAILED")
            raise GeminiMediaError("PROVIDER_GENERATION_FAILED", status, dispatch_confirmed=True)
        uri: str | None = None
        for node in _walk(payload.get("response", {})):
            candidate = node.get("uri")
            if isinstance(candidate, str) and candidate.startswith("https://"):
                uri = candidate
                break
        if uri is None:
            raise GeminiMediaError("PROVIDER_RESULT_MISSING", "video uri", dispatch_confirmed=True)
        data = self.binary_transport(uri, self._key, self.timeout)
        ensure_free_space(destination.parent, minimum_free_bytes=max(64 * 1024 * 1024, len(data) * 2))
        candidate_path = destination.with_suffix(destination.suffix + ".candidate")
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes(data)
        metadata = validate_video(candidate_path)
        os.replace(candidate_path, destination)
        metadata = validate_video(destination)
        return MediaResult(destination, self.provider, "veo-3.1-generate-preview", "predictLongRunning",
                           None, operation_name.rsplit("/", 1)[-1], "VEO_REFERENCE", 1, metadata)

    def generate_veo_video(self, *, prompt: str, references: list[Path], destination: Path,
                           mode: str, operation_name: str | None = None,
                           on_submitted: Callable[[str], None] | None = None) -> MediaResult:
        operation = operation_name or self.submit_veo(prompt=prompt, references=references, mode=mode)
        if operation_name is None and on_submitted:
            on_submitted(operation)
        return self.complete_veo(operation_name=operation, destination=destination)
