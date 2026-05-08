import os
from openai import AsyncOpenAI
from typing import Optional

_openai: Optional[AsyncOpenAI] = None

async def get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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
