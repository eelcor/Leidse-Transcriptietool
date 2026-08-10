"""Merge-logica: koppel STT-woorden aan diarisatie-sprekers en hersnijd de segmenten.

Puur en zonder zij-effecten (geen GPU, geen model, geen audio) — volledig unittestbaar.
Werkt over gewone datastructuren:
  - words: [{"start","end","text","probability"}, ...]  (STT-woorden, op tijd geordend)
  - turns: [{"start","end","speaker"}, ...]              (diarisatie-turns, rauwe labels)

Regels (zie ROADMAP.md / de opdracht):
  1. Elk woord krijgt de spreker met de grootste tijdsoverlap.
  2. Segmenten worden op sprekergrenzen hersneden: een segment bevat nooit twee sprekers.
  3. Gaten < min_gap binnen dezelfde spreker worden dichtgeplakt (op turn-niveau).
  4. Sprekerfragmenten < min_segment worden weggegooid; hun woorden gaan naar de buur.
  5. Woorden zonder enige overlap krijgen de spreker van het voorgaande woord.
  6. Labels zijn SPREKER_A, SPREKER_B, … op volgorde van eerste spreekmoment.
"""
from __future__ import annotations


def _overlap(a_start, a_end, b_start, b_end) -> float:
    """Overlap (seconden) tussen [a_start,a_end) en [b_start,b_end); 0 als geen timing."""
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return 0.0
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _stable_label(i: int) -> str:
    """0->SPREKER_A, 25->SPREKER_Z, 26->SPREKER_AA, … (robuust bij >26 sprekers)."""
    s = ""
    n = i + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord("A") + r) + s
    return f"SPREKER_{s}"


def coalesce_turns(turns: list[dict], min_gap: float) -> list[dict]:
    """Plak per spreker turns dicht die < min_gap uit elkaar liggen (regel 3). Sorteert op start."""
    by_spk: dict[str, list[dict]] = {}
    for t in turns:
        by_spk.setdefault(t["speaker"], []).append(t)
    out: list[dict] = []
    for spk, ts in by_spk.items():
        ts = sorted(ts, key=lambda x: x["start"])
        cur: dict | None = None
        for t in ts:
            if cur is not None and t["start"] - cur["end"] < min_gap:
                cur["end"] = max(cur["end"], t["end"])
            else:
                if cur is not None:
                    out.append(cur)
                cur = {"start": t["start"], "end": t["end"], "speaker": spk}
        if cur is not None:
            out.append(cur)
    return sorted(out, key=lambda x: x["start"])


def assign_word_speakers(words: list[dict], turns: list[dict]) -> list[str | None]:
    """Regel 1: elk woord -> spreker met de grootste overlap (None bij geen positieve overlap)."""
    labels: list[str | None] = []
    for w in words:
        best, best_ov = None, 0.0
        for t in turns:
            ov = _overlap(w.get("start"), w.get("end"), t["start"], t["end"])
            if ov > best_ov:
                best_ov, best = ov, t["speaker"]
        labels.append(best)
    return labels


def _fill_unassigned(labels: list[str | None]) -> list[str | None]:
    """Regel 5: woorden zonder overlap krijgen de spreker van het voorgaande woord
    (en, voor leidende gaten, van het eerstvolgende toegewezen woord)."""
    out = list(labels)
    last = None
    for i, l in enumerate(out):
        if l is None:
            if last is not None:
                out[i] = last
        else:
            last = l
    nxt = None
    for i in range(len(out) - 1, -1, -1):
        if out[i] is None:
            if nxt is not None:
                out[i] = nxt
        else:
            nxt = out[i]
    return out


def _runs(labels: list[str | None]) -> list[tuple[str | None, int, int]]:
    """Aaneengesloten runs van dezelfde spreker als (speaker, start_idx, end_idx) (inclusief)."""
    runs: list[tuple[str | None, int, int]] = []
    for i, spk in enumerate(labels):
        if runs and runs[-1][0] == spk:
            s, a, _ = runs[-1]
            runs[-1] = (s, a, i)
        else:
            runs.append((spk, i, i))
    return runs


def _run_duration(words: list[dict], a: int, b: int) -> float:
    """Duur van run words[a..b]; oneindig als er geen timing is (dan niet weggooien)."""
    starts = [words[i].get("start") for i in range(a, b + 1) if words[i].get("start") is not None]
    ends = [words[i].get("end") for i in range(a, b + 1) if words[i].get("end") is not None]
    if not starts or not ends:
        return float("inf")
    return max(ends) - min(starts)


def _apply_min_segment(words: list[dict], labels: list[str | None], min_segment: float) -> list[str | None]:
    """Regel 4: run korter dan min_segment -> woorden naar de buur (vorige, anders volgende)."""
    labels = list(labels)
    while True:
        runs = _runs(labels)
        if len(runs) <= 1:
            break
        changed = False
        for ri, (spk, a, b) in enumerate(runs):
            if _run_duration(words, a, b) < min_segment:
                if ri > 0:
                    target = runs[ri - 1][0]
                elif ri < len(runs) - 1:
                    target = runs[ri + 1][0]
                else:
                    continue
                for i in range(a, b + 1):
                    labels[i] = target
                changed = True
                break  # runs herbouwen na elke wijziging (kan cascaderen)
        if not changed:
            break
    return labels


def _segment_text(words: list[dict]) -> str:
    """Segmenttekst: woorden getrimd en met één spatie aaneen (deterministisch)."""
    return " ".join(w["text"].strip() for w in words if w.get("text", "").strip())


def merge(words: list[dict], turns: list[dict], min_gap: float = 0.5, min_segment: float = 0.5) -> dict:
    """Voer de volledige merge uit. Retourneert:
        {"segments": [{"start","end","speaker","text","words"}...],
         "speaker_map": {rauw_label: SPREKER_X},
         "num_labeled_speakers": n}
    Bij lege diarisatie (geen turns): één segment met speaker=None (alle woorden ongelabeld).
    """
    turns = coalesce_turns(turns, min_gap) if turns else []
    labels = _fill_unassigned(assign_word_speakers(words, turns))
    labels = _apply_min_segment(words, labels, min_segment)

    # Regel 6: stabiele labels op volgorde van eerste spreekmoment.
    order: list[str] = []
    for spk in labels:
        if spk is not None and spk not in order:
            order.append(spk)
    mapping = {raw: _stable_label(i) for i, raw in enumerate(order)}

    segments: list[dict] = []
    for spk, a, b in _runs(labels):
        seg_words = words[a : b + 1]
        starts = [w.get("start") for w in seg_words if w.get("start") is not None]
        ends = [w.get("end") for w in seg_words if w.get("end") is not None]
        segments.append({
            "start": min(starts) if starts else None,
            "end": max(ends) if ends else None,
            "speaker": mapping.get(spk) if spk is not None else None,
            "text": _segment_text(seg_words),
            "words": seg_words,
        })

    return {"segments": segments, "speaker_map": mapping, "num_labeled_speakers": len(mapping)}


def pick_speaker_clips(segments: list[dict], target: float = 4.0, max_gap: float = 0.4) -> dict[str, list[float]]:
    """Kies per spreker een goed hoorbaar fragment: het LANGSTE aaneengesloten stuk spraak
    (opeenvolgende woorden < max_gap uit elkaar), en daarvan tot `target` seconden vanaf het
    begin van dat stuk. Zo begint de clip op een heldere woord-inzet i.p.v. een zachte aanloop
    of een overlap. Retour: {SPREKER_X: [start, end]}. Puur en testbaar."""
    by_spk: dict[str, list[tuple[float, float]]] = {}
    for seg in segments:
        spk = seg.get("speaker")
        if not spk:
            continue
        for w in seg.get("words") or []:
            ws, we = w.get("start"), w.get("end")
            if ws is not None and we is not None:
                by_spk.setdefault(spk, []).append((ws, we))

    clips: dict[str, list[float]] = {}
    for spk, words in by_spk.items():
        words.sort()
        best: tuple[float, float] | None = None
        best_dur = -1.0
        run_start, prev_end = words[0]
        for ws, we in words[1:]:
            if ws - prev_end <= max_gap:              # nog steeds continu praten
                prev_end = max(prev_end, we)
            else:                                      # gat -> run afsluiten, evalueren
                if prev_end - run_start > best_dur:
                    best_dur = prev_end - run_start
                    best = (run_start, prev_end)
                run_start, prev_end = ws, we
        if prev_end - run_start > best_dur:
            best = (run_start, prev_end)
        if best:
            s, e = best
            clips[spk] = [round(s, 2), round(min(e, s + target), 2)]
    return clips


def labeled_transcript(segments: list[dict]) -> str:
    """Bouw een spreker-geprefixt transcript uit merge-segmenten:
        "SPREKER_A: …\nSPREKER_B: …". Ongelabelde segmenten krijgen geen prefix.
    (Gebruikt in fase 4 voor de LLM-context; puur en testbaar.)"""
    lines: list[str] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        spk = seg.get("speaker")
        lines.append(f"{spk}: {text}" if spk else text)
    return "\n".join(lines)
