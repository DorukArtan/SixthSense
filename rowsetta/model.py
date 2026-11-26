"""Step 4 - Model client with two backends.

Owner: TBD

OllamaBackend: local model through Ollama structured outputs, temperature 0.
GeminiBackend: commercial alternative (method E); key from GEMINI_API_KEY.
Both return a ModelResponse validated against MODEL_RESPONSE_SCHEMA plus a
ModelCall record (latency, token counts when the backend reports them).
"""

from __future__ import annotations

from typing import Protocol

from rowsetta.settings import Settings
from rowsetta.types import ModelCall, ModelResponse


class ModelBackend(Protocol):
    name: str
    model: str

    def generate(self, messages: list[dict]) -> tuple[ModelResponse, ModelCall]: ...


class OllamaBackend:
    name = "ollama"

    def __init__(self, settings: Settings):
        self.model = settings.ollama_model
        self.host = settings.ollama_host

    def generate(self, messages: list[dict]) -> tuple[ModelResponse, ModelCall]:
        raise NotImplementedError("OllamaBackend.generate")


class GeminiBackend:
    name = "gemini"

    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set (see .env.example)")
        self.model = settings.gemini_model
        self.api_key = settings.gemini_api_key

    def generate(self, messages: list[dict]) -> tuple[ModelResponse, ModelCall]:
        raise NotImplementedError("GeminiBackend.generate")


def make_backend(settings: Settings) -> ModelBackend:
    if settings.backend == "gemini":
        return GeminiBackend(settings)
    return OllamaBackend(settings)
