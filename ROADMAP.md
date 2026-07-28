# Roadmap

Losse, nog niet ingeplande verbeteringen. Bewust klein gehouden; alleen items met
een concreet integratiepunt in de huidige codebase.

## Spreker-diarisatie (wie zegt wat)

**Waarom.** Het transcript bevat nu géén sprekeridentificatie. De verslagprompt is
daarom expres terughoudend: sprekers worden alleen benoemd bij ≥95% zekerheid (zie
`PROMPTS.md`). Met diarisatie kunnen segments een `speaker`-label krijgen, waarna
verslagen betrouwbaar sprekers kunnen toewijzen.

**Waarom nog niet.** Pyannote (of gelijkwaardig) draait bij voorkeur op GPU en kost
extra VRAM + verwerkingstijd bovenop STT. Op de dev-box concurreert dat met de 4×V100
(Qwen) en de STT op de resterende capaciteit. Vandaar: expliciet opt-in.

**Scaffolding die er al staat.**
- Config-vlaggen (gereserveerd, standaard uit) in `backend/app/config.py`:
  `DIARIZATION_ENABLED`, `DIARIZATION_BACKEND`, `DIARIZATION_MODEL`, `HF_TOKEN`.
- Extensiehaak `backend/worker/diarize.py` met `apply_diarization(wav_path, segments)` —
  nu een no-op; contract gedocumenteerd (segments in → segments met `speaker` uit).
- Aanroep zit al in de pijplijn (`worker/worker.py`, direct ná STT), guarded en no-op
  by default.

**Fasering.**
1. Backend achter de haak (pyannote-3.1), alleen als `DIARIZATION_ENABLED=true`.
   Draai op een aparte GPU of serialiseer met STT via de bestaande semafoor.
2. Overlap speaker-turns met de STT-segments; zet per segment een label.
3. Frontend: sprekerlabels tonen bij "Toon tijdcodes"; prompt-regel versoepelen als er
   wél diarisatie is (dan mag toeschrijving op basis van de labels).
4. Kwaliteits-/resourcemeting: verwerkingstijd en VRAM per uur audio vastleggen.

**Aandachtspunten.** Pyannote-modellen zijn gated op HuggingFace (token nodig); model
lokaal cachen i.v.m. de "los van internet"-filosofie; diarisatie voegt privacygevoelige
structuur toe (wie-zegt-wat) — houdt binnen dezelfde bewaartermijn/anonimiteit.

## Beveiliging (netwerk-/infralaag)

De applicatielaag is aangepakt (zie `SECURITY.md`). Buiten de app, als roadmap:
- Rate-limiting / basale abuse-bescherming (bv. per-IP limiet op `POST /api/sessions`,
  `/upload`, `/reports`) — kan met de bestaande Redis. Nu bewust achterwege gelaten omdat
  het systeem op een geïsoleerd VLAN staat; toevoegen zodra bredere toegang speelt.
- ffmpeg draait op niet-vertrouwde media (bekende CVE-klasse). Overweeg een seccomp-/
  resource-sandbox of een aparte, rechtenloze container voor transcodering.
- Reverse-proxy WAF / fail2ban op de rand als het systeem ooit buiten het VLAN komt.
