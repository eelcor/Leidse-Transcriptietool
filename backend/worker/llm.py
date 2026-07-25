"""Verslag genereren via het bestaande, OpenAI-compatibele Qwen-endpoint.

We hosten hier GEEN LLM: dit praat met het al draaiende endpoint via env-vars
(LLM_BASE_URL / LLM_MODEL / LLM_API_KEY). Qwen's grote contextvenster dekt
vrijwel elk transcript in één keer.
"""
from __future__ import annotations

import logging

from app.config import get_settings

log = logging.getLogger("transcribe.llm")


async def generate(messages: list[dict[str, str]]) -> str:
    from openai import AsyncOpenAI

    s = get_settings()
    client = AsyncOpenAI(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        timeout=s.llm_timeout_seconds,
    )
    resp = await client.chat.completions.create(
        model=s.llm_model,
        messages=messages,
        temperature=s.llm_temperature,
    )
    return (resp.choices[0].message.content or "").strip()
