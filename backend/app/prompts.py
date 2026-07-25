"""Laad de letterlijke prompt-teksten uit PROMPTS.md (single source of truth).

We parsen het markdown-bestand en pakken per sectie het eerste ```-codeblok.
Zo blijft PROMPTS.md leidend en hoeven prompts niet gedupliceerd te worden in code.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .config import get_settings

# Kernel-key -> (deel van de kop in PROMPTS.md, UI-label)
SECTIONS: dict[str, tuple[str, str]] = {
    "samenvatting": ("## 1. Samenvatting", "Samenvatting"),
    "verslag": ("## 2. Verslag", "Verslag (uitgewerkt)"),
    "actiepunten": ("## 3. Actiepunten", "Actiepunten"),
    "afspraken": ("## 4. Afspraken", "Afspraken"),
    "besluiten": ("## 5. Besluiten", "Besluiten"),
    "aandachtspunten": ("## 6. Aandachtspunten", "Aandachtspunten"),
    "volledig": ("## 7. Volledig verslag", "Volledig verslag"),
}

_BASE_HEADING = "## Gedeelde basis-instructie"


def _first_code_block_after(text: str, heading: str) -> str:
    idx = text.find(heading)
    if idx == -1:
        raise KeyError(f"Kop niet gevonden in PROMPTS.md: {heading!r}")
    rest = text[idx + len(heading):]
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", rest, re.DOTALL)
    if not m:
        raise KeyError(f"Geen codeblok gevonden na kop: {heading!r}")
    return m.group(1).strip()


@lru_cache
def _load_raw() -> str:
    with open(get_settings().prompts_file, "r", encoding="utf-8") as f:
        return f.read()


@lru_cache
def base_instruction() -> str:
    return _first_code_block_after(_load_raw(), _BASE_HEADING)


@lru_cache
def section_task(key: str) -> str:
    if key not in SECTIONS:
        raise KeyError(f"Onbekende sectie: {key!r}")
    heading, _ = SECTIONS[key]
    return _first_code_block_after(_load_raw(), heading)


def available_sections() -> list[dict[str, str]]:
    """Voor de frontend: lijst van keuzeopties."""
    return [{"key": k, "label": label} for k, (_, label) in SECTIONS.items()]


def build_messages(
    transcript: str,
    kinds: list[str] | None,
    custom_prompt: str | None,
    context: str | None,
) -> list[dict[str, str]]:
    """Bouw de OpenAI-chat messages: één system (basis + taak), één user (context + transcript)."""
    base = base_instruction()

    if custom_prompt:
        task = custom_prompt.strip()
    elif kinds:
        # "volledig" heeft voorrang: één alles-in-één prompt.
        if "volledig" in kinds:
            task = section_task("volledig")
        else:
            parts = [section_task(k) for k in kinds if k in SECTIONS]
            if not parts:
                raise ValueError("Geen geldige secties opgegeven")
            if len(parts) == 1:
                task = parts[0]
            else:
                task = (
                    "Voer de onderstaande deeltaken uit en lever de secties na elkaar op, "
                    "elk met de aangegeven kop.\n\n" + "\n\n---\n\n".join(parts)
                )
    else:
        raise ValueError("Geef 'kinds' of 'custom_prompt' op")

    system = f"{base}\n\n{task}"

    user_parts: list[str] = []
    if context and context.strip():
        user_parts.append("Context (door gebruiker aangeleverd):\n" + context.strip())
    user_parts.append("Transcript:\n" + transcript)
    user = "\n\n".join(user_parts)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
