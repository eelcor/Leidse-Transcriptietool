"""Fase 3 — merge-logica. Pure tests, geen GPU/model/audio.

Dekt de door de opdracht gevraagde randgevallen: overlap midden in een woord, sprekerwissel
midden in een Whisper-segment, overlappende spraak, een woord zonder overlap, leidend woord
zonder overlap, min_segment-weggooi, min_gap-dichtplakken, labelvolgorde en lege diarisatie.
"""
from app.diarize.merge import (
    coalesce_turns,
    labeled_transcript,
    merge,
)


def W(start, end, text):
    return {"start": start, "end": end, "text": text, "probability": 0.9}


def T(start, end, spk):
    return {"start": start, "end": end, "speaker": spk}


def _speakers(res):
    return [s["speaker"] for s in res["segments"]]


def _texts(res):
    return [s["text"] for s in res["segments"]]


# 1) Lege diarisatie -> één ongelabeld segment, geen sprekers.
def test_empty_diarization():
    res = merge([W(0, 1, "a"), W(1, 2, "b")], turns=[])
    assert res["num_labeled_speakers"] == 0
    assert len(res["segments"]) == 1
    assert res["segments"][0]["speaker"] is None
    assert res["segments"][0]["text"] == "a b"


# 2) Eén spreker -> één segment SPREKER_A.
def test_single_speaker():
    res = merge([W(0, 1, "a"), W(1, 2, "b")], [T(0, 2, "S0")])
    assert res["num_labeled_speakers"] == 1
    assert _speakers(res) == ["SPREKER_A"]
    assert _texts(res) == ["a b"]


# 3) Twee sprekers, schone knip -> twee segmenten A, B.
def test_two_speakers_clean_split():
    res = merge([W(0, 1, "a"), W(1, 2, "b")], [T(0, 1, "S0"), T(1, 2, "S1")])
    assert _speakers(res) == ["SPREKER_A", "SPREKER_B"]
    assert _texts(res) == ["a", "b"]


# 4) Sprekerwissel MIDDEN in een Whisper-segment -> segment wordt hersneden.
def test_speaker_change_mid_segment_recut():
    words = [W(0.0, 0.4, "Hallo"), W(0.4, 0.8, "allen"), W(0.8, 1.2, "ja"), W(1.2, 1.6, "zeker")]
    turns = [T(0.0, 0.8, "S0"), T(0.8, 1.6, "S1")]
    res = merge(words, turns)
    assert _speakers(res) == ["SPREKER_A", "SPREKER_B"]
    assert _texts(res) == ["Hallo allen", "ja zeker"]


# 5) Overlap MIDDEN in een woord -> woord gaat naar de spreker met de grootste overlap.
def test_overlap_in_middle_of_word():
    # "mid" straddelt de grens maar overlapt S0 meer (0.6) dan S1 (0.4).
    words = [W(0.3, 1.3, "mid"), W(1.4, 2.0, "end")]
    turns = [T(0.0, 0.9, "S0"), T(0.9, 2.2, "S1")]
    res = merge(words, turns)
    assert _speakers(res) == ["SPREKER_A", "SPREKER_B"]
    assert _texts(res) == ["mid", "end"]


# 6) Overlappende spraak van twee sprekers -> grootste overlap wint.
def test_overlapping_speech():
    words = [W(0.5, 1.0, "a"), W(1.45, 2.0, "y")]
    turns = [T(0.0, 1.6, "S0"), T(1.4, 3.0, "S1")]   # overlapgebied [1.4, 1.6]
    res = merge(words, turns)
    # 'y' zit in het overlapgebied maar overlapt S1 (0.55) meer dan S0 (0.15).
    assert _speakers(res) == ["SPREKER_A", "SPREKER_B"]
    assert res["segments"][1]["text"] == "y"


# 7) Woord zonder enige overlap -> spreker van het VOORGAANDE woord.
def test_word_without_overlap_takes_previous():
    words = [W(0, 1, "a"), W(1.0, 1.2, "gap"), W(3, 4, "b")]
    turns = [T(0, 1, "S0"), T(3, 4, "S1")]
    res = merge(words, turns, min_gap=0.0)
    # 'gap' overlapt niets -> krijgt S0 (vorige) en zit dus in segment A.
    assert _texts(res) == ["a gap", "b"]
    assert _speakers(res) == ["SPREKER_A", "SPREKER_B"]


# 8) Leidend woord zonder overlap -> backfill vanaf het eerstvolgende toegewezen woord.
def test_leading_word_without_overlap_backfills():
    words = [W(0.0, 0.4, "lead"), W(1, 2, "a")]
    turns = [T(1, 2, "S0")]
    res = merge(words, turns)
    assert len(res["segments"]) == 1
    assert _speakers(res) == ["SPREKER_A"]
    assert _texts(res) == ["lead a"]


# 9) Sprekerfragment < min_segment -> weggegooid; woorden naar de buur.
def test_min_segment_discards_tiny_fragment():
    words = [W(0, 1, "a"), W(1.0, 1.2, "blip"), W(1.3, 2.5, "b")]
    turns = [T(0, 1.0, "S0"), T(1.0, 1.2, "S1"), T(1.3, 2.5, "S0")]
    # min_gap=0 zodat de twee S0-turns niet coalesceren en 'blip' echt S1 wint.
    res = merge(words, turns, min_gap=0.0, min_segment=0.5)
    assert res["num_labeled_speakers"] == 1
    assert len(res["segments"]) == 1
    assert _speakers(res) == ["SPREKER_A"]
    assert _texts(res) == ["a blip b"]


# 10) Labelvolgorde op EERSTE spreekmoment, niet op het rauwe pyannote-label.
def test_labels_by_first_speaking_moment():
    words = [W(0, 1, "a"), W(1, 2, "b")]
    turns = [T(0, 1, "SPEAKER_02"), T(1, 2, "SPEAKER_00")]
    res = merge(words, turns)
    # SPEAKER_02 spreekt eerst -> SPREKER_A (ondanks het hogere rauwe nummer).
    assert res["speaker_map"] == {"SPEAKER_02": "SPREKER_A", "SPEAKER_00": "SPREKER_B"}
    assert _speakers(res) == ["SPREKER_A", "SPREKER_B"]


# 11) min_gap: dezelfde spreker met een klein gat wordt dichtgeplakt (turn-niveau).
def test_coalesce_turns_same_speaker_small_gap():
    merged = coalesce_turns([T(0, 1, "S0"), T(1.3, 2.0, "S0")], min_gap=0.5)
    assert len(merged) == 1
    assert merged[0]["start"] == 0 and merged[0]["end"] == 2.0


def test_coalesce_turns_keeps_large_gap_and_other_speakers():
    merged = coalesce_turns([T(0, 1, "S0"), T(1.6, 2.0, "S0")], min_gap=0.5)
    assert len(merged) == 2                       # gat 0.6 >= 0.5 -> niet samengevoegd
    merged2 = coalesce_turns([T(0, 1, "S0"), T(1.1, 2, "S1")], min_gap=0.5)
    assert len(merged2) == 2                       # andere sprekers nooit samenvoegen


# 12) labeled_transcript: prefix per beurt; ongelabeld zonder prefix.
def test_labeled_transcript():
    res = merge([W(0, 1, "hoi"), W(1, 2, "daar")], [T(0, 1, "S0"), T(1, 2, "S1")])
    assert labeled_transcript(res["segments"]) == "SPREKER_A: hoi\nSPREKER_B: daar"
    # Lege diarisatie -> geen prefix.
    res2 = merge([W(0, 1, "hoi"), W(1, 2, "daar")], turns=[])
    assert labeled_transcript(res2["segments"]) == "hoi daar"
