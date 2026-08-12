from .elevenlabs import ElevenLabsProvider
from .typecast import TypecastProvider

def provider_for(name: str):
    return {"elevenlabs": ElevenLabsProvider, "typecast": TypecastProvider}[name]()
