"""ChatNVIDIA pointed at Nemotron Parse. The key is read from the environment."""
from __future__ import annotations

from langchain_nvidia_ai_endpoints import ChatNVIDIA

from app.config import Settings

PARSE_MODEL = "nvidia/nemotron-parse"


class MissingNvidiaKey(Exception):
    """NVIDIA_PARSE_API_KEY was not in the environment. Run the command under `doppler run`."""


def parse_client(settings: Settings | None = None) -> ChatNVIDIA:
    """The user's ChatNVIDIA constructor: model, key, temperature, top_p, max_completion_tokens."""
    settings = settings or Settings()
    key = settings.nvidia_parse_api_key.strip()
    if not key:
        raise MissingNvidiaKey("NVIDIA_PARSE_API_KEY is empty. Run under Doppler: doppler run -- <command>")
    return ChatNVIDIA(
        model=settings.nvidia_parse_model or PARSE_MODEL,
        api_key=key,
        temperature=0,
        top_p=1,
        max_completion_tokens=4096,
    )
