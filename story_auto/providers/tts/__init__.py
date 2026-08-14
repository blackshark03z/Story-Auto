from .elevenlabs import ElevenLabsProvider
from .kokoro_local import KokoroLocalProvider
from .typecast import TypecastProvider

def provider_for(name: str):
    return {"elevenlabs": ElevenLabsProvider, "typecast": TypecastProvider,
            "kokoro_local": KokoroLocalProvider}[name]()
