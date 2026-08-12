from __future__ import annotations

import os
from story_auto.core.audio.errors import AudioPipelineError


def provider_keys(provider: str) -> list[str]:
    """Read only ephemeral environment credentials; values never enter diagnostics."""
    name = {"elevenlabs": "ELEVENLABS_API_KEY", "typecast": "TYPECAST_API_KEY"}.get(provider)
    if not name: raise ValueError("unsupported provider")
    keys = [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]
    if not keys: raise AudioPipelineError("CREDENTIAL_MISSING", provider=provider, stage="credentials")
    return keys
