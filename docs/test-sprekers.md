# Testverslag sprekersidentificatie

Bevindingen van de bouw en test van de spreker-diarisatie (branch `spreker-identificatie`),
peildatum 2026-08-10. Bevat geen vergaderinhoud — alleen metingen en structuur.

## Opzet

- **Hardware:** dev-box met 4× Tesla V100 (16 GB, gedeeld met het Qwen-LLM) + 1× Quadro P1000.
  STT (faster-whisper large-v2) op een V100; diarisatie (pyannote) gepind op één V100 via CDI.
- **Testmateriaal** (lokaal, `samples/`, niet in git):
  - opname A — browseropname (webm/opus, laptop, veraf), ~77 min, 7 deelnemers (meerdere stil).
  - opname B — iPhone-opname (m4a/AAC), ~50 min, meerdere actieve sprekers.

## Geautomatiseerd

- `PYTHONPATH=. pytest` volledig groen (**62 passed**), zonder Redis/GPU.
- Merge-logica (fase 3): 14 tabelgedreven unittests, incl. overlap midden in een woord,
  sprekerwissel midden in een Whisper-segment, overlappende spraak, woord zonder overlap,
  leidend woord zonder overlap, `min_segment`-weggooi, `min_gap`-dichtplakken, labelvolgorde en
  lege diarisatie.
- Regressie: met `DIARIZE_BACKEND=none` verandert er niets — geen diarizations-rij, geen job,
  segments blijven byte-voor-byte `{start,end,text}` (unit-getest via `segments_as_dicts`).
- Zacht falen: een exception in de diarizer laat de job niet klappen (rij → `failed`, transcript
  blijft bruikbaar). Unit-getest.
- Namen: in `SPEAKER_NAMES_MODE=placeholder` komt geen naam in de opgeslagen payload; in `direct`
  wel (in de context). Beide via API-tests bevestigd.

## Handmatig (echte opnames, end-to-end via de app)

Volledige doorloop opname B (m4a, ~50 min), auto-detectie, met verslag:

- **STT:** ~9 min voor 77 min / ~5 min voor 50 min audio (~8–10× realtime, GPU).
- **Diarisatie (3.1):** ~1–1,5 min voor 50–77 min (~50× realtime, GPU); piek-VRAM ~2 GB.
- **Verslag:** ~3–4 min (Qwen), draait ná de diarisatie zodat het sprekerlabels heeft.
- **Volgorde en resultaat kloppen:** transcript met sprekerlabels, verslag met `SPREKER_A/B/…`,
  namen client-side ingevuld (placeholder → niet in DB), Markdown- én Word-export met namen.
- **"Opnieuw indelen"** met een afwijkend aantal getest — werkt via dezelfde SSE/poll-flow.

### Sprekeraantal: auto vs. forceren

Het forceren van een aantal (`participants` → `min/max_speakers`) is tweesnijdend:
- **te hoog** → over-segmentatie in korte "spookspreker"-fragmenten;
- **te laag** → één cluster slokt bijna alle spraak op (op opname B propte `participants=4`
  ~48 van 50 min in één spreker).
**Aanbeveling:** laat het veld leeg (auto) tenzij je het aantal *actieve* sprekers zeker weet.

### Audiokwaliteit is bepalend

Opname B (dichterbij, helderder) gaf 5 nette sprekers; opname A (laptop, veraf, veel overlap
en stille deelnemers) gaf 3 duidelijke + veel korte fragmenten. Het verschil zit in de audio,
niet in de tool.

## Experiment 1 — custom audio-DSP (conclusie: geen winst)

Getest op een 8-min-fragment van beide opnames: `none` (baseline), `afftdn` (ffmpeg-denoise),
`wpe` (dereverberatie via nara_wpe), `stereo`. Proxy's: Whisper-woord-confidence (WER-proxy) en
diarisatie-uitkomst.

| Opname | Variant | Woord-confidence (med.) | #sprekers |
|---|---|---|---|
| B (m4a) | none | 0,820 | 5 |
| B (m4a) | afftdn | 0,796 (slechter) | 5 |
| B (m4a) | wpe | 0,815 (~gelijk) | 5 |
| A (webm) | none | 0,801 | 3 |
| A (webm) | afftdn | 0,771 (slechter) | 3 |
| A (webm) | wpe | 0,795 (~gelijk) | 3 |

**Conclusie:** DSP verbetert de diarisatie niet en helpt de WER-proxy niet; `afftdn` verslechtert
Whisper zelfs (artefacten, ~30% churn) — conform de BOUWPROMPT-waarschuwing tegen agressieve
bewerking. Single-channel WPE is te zwak; de echte degradatie is overlap/afstand, niet galm.
Stereo is moot: STT en pyannote downmixen intern naar mono.

## Experiment 2 — pyannote community-1 (conclusie: winst; opt-in gemaakt)

community-1 (pyannote 4.x, VBx-clustering) vs 3.1 op **dezelfde volledige m4a** (GPU):

| Model | #sprekers | Spreektijd (s) |
|---|---|---|
| 3.1 | 6 | 1049 · 834 · 469 · 417 · 142 · **55** |
| community-1 | 5 | 1075 · 834 · 473 · 432 · 152 |
| community-1 *exclusive* | 5 | 990 · 779 · 437 · 402 · 134 |

**community-1 vermindert de over-segmentatie** (laat de spookspreker van 55 s weg; strakke
5-sprekers-indeling; hoofdsprekers identiek). Plus een *exclusive* modus (elk moment één spreker)
die de merge/overgangen gladstrijkt. **End-to-end door de app geverifieerd** (5 schone sprekers,
clips gegenereerd).

**Integratie (opt-in, 3.1 blijft default):**
- `DIARIZE_MODEL=pyannote/speaker-diarization-community-1` + `DIARIZE_EXCLUSIVE`.
- pyannote 4 vereist torch ≥ 2.8 → **cu126**-build (behoudt sm_70/V100; cu130 dropt Volta).
  Dockerfile.diarize is geparametriseerd (`DIARIZE_TORCH_SPEC/INDEX_URL/REQS`).
- pyannote 4's `torchcodec` laadt niet (FFmpeg/CUDA-mismatch); de backend **voert de golfvorm zelf
  in** (16 kHz-wav) → torchcodec wordt omzeild, aan ffmpeg verandert niets. De resterende
  torchcodec-tracebacks in de log zijn onschuldige import-ruis.

## Opruimen / bewaartermijn (testpunt 10)

De `diarizations`-tabel hangt met `cascade="all, delete-orphan"` aan de sessie; de opruimservice
verwijdert bij het verlopen van een sessie ook de diarisatie-rijen. Afgedekt door het cascade-
ontwerp; geen aparte opschoning nodig.

## Openstaand / aanbevelingen

- **Slim luisterfragment** per spreker (langste aaneengesloten spraak) geïmplementeerd; verbetert
  hoorbaarheid duidelijk t.o.v. "begin van het langste segment".
- **community-1 aanraden** boven 3.1 waar torch 2.8+cu126 kan; het lost de over-segmentatie beter op.
- **DSP niet verder uitwerken** voor deze opnames; investeer eerder in mic-plaatsing/opnamekwaliteit.
- Cosmetisch: torchcodec-import-ruis in de diarize-log kan onderdrukt worden.
