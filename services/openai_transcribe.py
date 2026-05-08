import os
from openai import AsyncOpenAI
from typing import Optional

# ── Client for Ollama Cloud (OpenAI-compatible endpoint) ──
_ollama: Optional[AsyncOpenAI] = None

async def get_ollama_client() -> AsyncOpenAI:
    """Lazy-init Ollama Cloud/OpenAI-compatible client for local LLM."""
    global _ollama
    if _ollama is None:
        base_url = os.getenv("OLLAMA_CLOUD_BASE_URL", "http://localhost:11434/v1")
        api_key = os.getenv("OLLAMA_CLOUD_API_KEY", "not-needed-for-local")
        kwargs = {"base_url": base_url}
        if api_key and api_key != "not-needed-for-local":
            kwargs["api_key"] = api_key
        else:
            # Ollama local doesn't need authentication
            kwargs["api_key"] = "ollama"
        _ollama = AsyncOpenAI(**kwargs)
    return _ollama

# ── Client for OpenAI (Whisper + GPT-4o for extraction) ──
_openai: Optional[AsyncOpenAI] = None

async def get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _openai = AsyncOpenAI(api_key=key)
    return _openai

async def transcribe_audio(ogg_path: str) -> str:
    """Transcribe an OGG voice file via Whisper-1."""
    client = await get_openai()
    with open(ogg_path, "rb") as f:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",
        )
    return transcript or ""
