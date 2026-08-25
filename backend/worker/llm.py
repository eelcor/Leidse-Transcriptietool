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
    # Reasoning/"thinking" standaard uit: anders genereert een reasoning-model (Qwen3) eerst een
    # groot <think>-blok, wat op lange transcripten de timeout overschrijdt. Meegegeven via
    # chat_template_kwargs (llama.cpp --jinja); onbekende velden worden door het endpoint genegeerd.
    extra_body = {} if s.llm_enable_thinking else {"chat_template_kwargs": {"enable_thinking": False}}
    resp = await client.chat.completions.create(
        model=s.llm_model,
        messages=messages,
        temperature=s.llm_temperature,
        extra_body=extra_body,
    )
    return (resp.choices[0].message.content or "").strip()
