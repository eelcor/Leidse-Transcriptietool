# Roadmap

Losse, nog niet ingeplande verbeteringen. Bewust klein gehouden; alleen items met
een concreet integratiepunt in de huidige codebase.

## Spreker-diarisatie (wie zegt wat) — GEÏMPLEMENTEERD (opt-in)

Sprekerherkenning ("wie zegt wat") is er, als **optionele** stap. Standaard **uit**
(`DIARIZE_BACKEND=none`) → geen enkel gedragsverschil. Aanzetten en configureren: zie
[`deploy/DEPLOY.md`](deploy/DEPLOY.md) ("Sprekerdiarisatie"); test-/meetbevindingen:
[`docs/test-sprekers.md`](docs/test-sprekers.md).

**Hoe het werkt.** Woord-timestamps uit STT → pyannote-diarisatie (aparte worker op een eigen
queue, torch/pyannote los van de lichte basis-worker) → pure merge-logica koppelt woorden aan
sprekers en hersnijdt de segments → verslag ná de diarisatie met labels `SPREKER_A/B/…`. Namen
worden client-side ingevuld (placeholder: niet in de DB) of meegegeven aan het LLM (direct).
Resultaat in een aparte tabel `diarizations` (geen migraties).

**Modellen.** `speaker-diarization-3.1` (default) of het nieuwere **community-1** (pyannote 4.x,
VBx-clustering — telt sprekers nauwkeuriger, minder spookspreker-fragmenten, plus een *exclusive*
modus). community-1 vereist torch ≥ 2.8 (cu126-build behoudt sm_70/V100).

**Vervolg / open.**
- community-1 breder inzetten (het lost de over-segmentatie beter op dan 3.1).
- Cosmetisch: torchcodec-import-ruis in de diarize-log onderdrukken.
- Onderzocht en afgevoerd: **custom audio-DSP** (dereverb/denoise) gaf geen WER- of
  diarisatiewinst op de testopnames (zie test-sprekers.md).

## Beveiliging (netwerk-/infralaag)

De applicatielaag is aangepakt (zie `SECURITY.md`). Buiten de app, als roadmap:
- Rate-limiting / basale abuse-bescherming (bv. per-IP limiet op `POST /api/sessions`,
  `/upload`, `/reports`) — kan met de bestaande Redis. Nu bewust achterwege gelaten omdat
  het systeem op een geïsoleerd VLAN staat; toevoegen zodra bredere toegang speelt.
- ffmpeg draait op niet-vertrouwde media (bekende CVE-klasse). Overweeg een seccomp-/
  resource-sandbox of een aparte, rechtenloze container voor transcodering.
- Reverse-proxy WAF / fail2ban op de rand als het systeem ooit buiten het VLAN komt.
