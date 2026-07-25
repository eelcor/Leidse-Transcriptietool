"""Live injectie-evaluatie tegen het echte LLM-endpoint.

Draait elke case uit injection_cases door de verslag-prompt (build_messages) en
het LLM, en beoordeelt of de injectie is genotuleerd (RESISTED) of uitgevoerd (OBEYED).

Vereist een bereikbaar LLM-endpoint (LLM_BASE_URL / LLM_MODEL). Dit is GEEN CI-test
(non-deterministisch); draai handmatig:

    cd backend
    LLM_BASE_URL=http://localhost:8033/v1 LLM_MODEL=Qwen3.6-27B \
      PROMPTS_FILE=$PWD/../PROMPTS.md PYTHONPATH=. python tests/injection_eval.py
"""
import asyncio
import sys

from app.prompts import build_messages
from tests.injection_cases import CASES, judge
from worker import llm


async def run_case(case: dict) -> tuple[dict, str, str]:
    messages = build_messages(case["transcript"], ["samenvatting"], None, None)
    try:
        out = await llm.generate(messages)
    except Exception as exc:  # endpoint niet bereikbaar
        return case, f"<FOUT: {type(exc).__name__}: {exc}>", "FOUT"
    return case, out, judge(out, case)


async def main() -> int:
    print(f"Injectie-evaluatie — {len(CASES)} cases\n" + "=" * 60)
    results = []
    for case in CASES:
        c, out, verdict = await run_case(case)
        results.append(verdict)
        icon = {"RESISTED": "✅", "OBEYED": "❌", "ONZEKER": "⚠️", "FOUT": "💥"}.get(verdict, "?")
        print(f"\n{icon} [{verdict}] {c['name']}")
        print(f"   injectie: {c['transcript'][:90]}")
        snippet = " ".join(out.split())[:220]
        print(f"   verslag : {snippet}")

    print("\n" + "=" * 60)
    n = len(results)
    ok = results.count("RESISTED")
    bad = results.count("OBEYED")
    unc = results.count("ONZEKER")
    print(f"RESISTED {ok}/{n} · OBEYED {bad} · ONZEKER {unc}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
