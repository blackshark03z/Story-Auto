"""Load-only Kokoro readiness probe executed by Kokoro's own interpreter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def run(request_path: Path, result_path: Path) -> None:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        from kokoro import KModel, KPipeline
        model = KModel(repo_id=request["model_repo"], config=request["config_path"],
                       model=request["model_path"]).to(request["device"]).eval()
        pipeline = KPipeline(lang_code=request["language"], repo_id=request["model_repo"],
                             model=model, device=request["device"])
        voice = pipeline.load_voice(request["voice_path"])
        if voice is None or not getattr(voice, "numel", lambda: 0)():
            raise RuntimeError("empty voice asset")
        _atomic_json(result_path, {"schema_version": "story-auto-kokoro-probe-result/1.0.0",
                                   "status": "READY"})
    except Exception:
        _atomic_json(result_path, {"schema_version": "story-auto-kokoro-probe-result/1.0.0",
                                   "status": "RUNTIME_LOAD_FAILED"})
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    run(args.request, args.result)


if __name__ == "__main__":
    main()
