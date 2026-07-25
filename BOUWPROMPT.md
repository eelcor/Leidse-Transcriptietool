# Bouwprompt — Anonieme transcriptie-webapp

> Geef deze prompt aan een ontwikkelaar of aan een AI-coding-agent (bijv. Claude Code)
> als startopdracht. De architectuurkeuzes bovenaan zijn al vastgelegd; de open
> keuzes staan in `OPEN-VRAGEN.md`.

## Rol & doel

Bouw een **simpele, laagdrempelige en schaalbare webapp** waarmee collega's **anoniem**
(zonder login of account) transcripties laten maken van geluidsopnames. De gebruiker
kan een bestand uploaden óf direct in de browser opnemen. Na verwerking krijgt de
gebruiker een transcript en optioneel een uitgewerkt verslag op basis van een gekozen
of eigen prompt.

Kernwaarden, in volgorde: **privacy/anonimiteit → laagdrempeligheid → kwaliteit van
Nederlandse transcriptie → schaalbaarheid**.

## Vastgelegde architectuurkeuzes

| Onderwerp | Keuze |
|---|---|
| Spraak-naar-tekst | **NVIDIA Canary 1B v2** (zelf-gehost via NeMo), model configureerbaar |
| Verslag-/samenvatting-LLM | **Bestaand Qwen3.6-27b endpoint hergebruiken** (OpenAI-compatibel) — géén nieuwe LLM hosten |
| Bewaartermijn | **Automatisch verwijderen 2 werkdagen ná verwerking** (audio + transcript; weekenden tellen niet mee) |
| Deployment | **Docker Compose op één VM**, met een pad naar opschaling |

## Aanbevolen techniek-stack (mag onderbouwd afwijken)

- **Frontend:** één lichte SPA of zelfs vanilla HTML/JS/CSS. Geen zware build-tooling
  tenzij nodig. Recorder via de browser `MediaRecorder`-API (Opus in WebM/OGG — klein
  en efficiënt).
- **API/backend:** Python **FastAPI**.
- **Wachtrij:** **Redis** + een lichte worker-library (arq, RQ of Celery). De API zet
  jobs op de queue; workers verwerken ze. Dit is de schaalbaarheids-as: workers kun je
  later horizontaal bijzetten of naar een GPU-pool verplaatsen.
- **STT-model:** **NVIDIA Canary 1B v2** via de **NeMo-toolkit** (`ASRModel.from_pretrained`).
  Ondersteunt Nederlands (25 EU-talen), CC-BY-4.0, ~978M params, doet automatisch
  long-form chunking (1s overlap, boven ~40s) — dus zelf geen segmentatie nodig. Input
  is 16kHz mono wav/flac, dus de worker moet met **ffmpeg** naar 16kHz mono resamplen.
  Maak het model configureerbaar via env-var. **Whisper is expliciet níet de default:**
  Whisper large-v3 heeft gedocumenteerde regressies (herhalingen/hallucinaties) t.o.v.
  v2; bied faster-whisper (large-v2) alleen als optionele fallback. Overweeg optioneel
  sprekerdiarisatie (pyannote) en woord-timestamps — zie open vragen.
- **Verslag-LLM:** **hergebruik het bestaande, al draaiende Qwen3.6-27b endpoint** (OpenAI-
  compatibel). Host géén nieuwe LLM. De app praat via env-vars (`LLM_BASE_URL`,
  `LLM_MODEL`, `LLM_API_KEY`) met dat endpoint, zodat dev/prod hetzelfde werken en het
  model verwisselbaar blijft. Het 256K-contextvenster van Qwen betekent dat zelfs lange
  transcripten in één keer verwerkt kunnen worden; val alleen terug op chunking/map-reduce
  als een transcript het venster overschrijdt.
- **Metadata/DB:** **PostgreSQL** (of SQLite voor de eerste versie) voor sessies, jobs
  en status. **Geen** persoonsgegevens opslaan.
- **Opslag audio/transcript:** lokaal volume (of MinIO). Bestanden bij een sessie-ID.

## GPU- & resource-context (belangrijk)

De verwerking moet passen binnen wat er náást de bestaande LLM's vrij is:

- **Dev-omgeving:** 4×V100 zijn volledig bezet door Qwen3.6-27b (256K context). Voor STT
  is alleen een **Quadro P1000 (4GB, Pascal)** beschikbaar. Dat is krap: Canary wil
  ~6GB om te laden en Pascal is zwak in fp16. Verwacht dat je op dev **int8/lagere
  precisie** of een **CPU-fallback** nodig hebt om te kunnen testen. Maak de STT-device
  en -precisie daarom **configureerbaar** (`STT_DEVICE`, `STT_COMPUTE_TYPE`) met een
  werkende CPU-fallback.
- **Prod-omgeving:** RTX Pro 6000 (96GB) draait Qwen3.6-27b; **~10GB vrij**. Canary past
  daarin, maar STT deelt de kaart met de LLM. **Begrens STT-concurrency** (default: 1
  gelijktijdige STT-job, via env-var) zodat piek-VRAM voorspelbaar blijft en Qwen niet
  uit het geheugen wordt gedrukt. De queue vangt de rest op.
- De verslag-LLM verbruikt **geen extra VRAM** in dit project: het is het bestaande
  Qwen-endpoint.

## Functionele eisen

### 1. Startpagina (super laagdrempelig)
- Geen login, geen cookies-muur, geen persoonsgegevens. Direct bruikbaar.
- Twee duidelijke paden naast elkaar: **"Bestand uploaden"** en **"Nu opnemen"**.
- Toegankelijk (WCAG-basis), NL-talig, werkt op mobiel en desktop.

### 2. In-browser recorder
- Opnemen via `MediaRecorder` naar **Opus/WebM** (efficiënt, klein). Streef mono en een
  bitrate rond 24–32 kbps (spraak) na; dat is ruim voldoende voor ASR en houdt uploads klein.
- Bouw de audioketen met de **Web Audio API**: `getUserMedia` → `MediaStreamSource` →
  bewerkingsknopen → bestemming voor opname. Zo kun je meten en bijsturen vóór encoding.

**VU-meter + gevoeligheid**
- **Live VU-meter** via een `AnalyserNode`: toon het niveau (RMS/piek) realtime als een
  balk. Markeer visueel drie zones: te zacht / goed / clipping (rood). Dit is de
  belangrijkste feedback voor de gebruiker.
- **Gevoeligheidsknop (sensitivity):** één duidelijke slider die de input-gain regelt via
  een `GainNode` vóór de meter en de encoder. De gebruiker draait tot de VU-meter mooi in
  de "goede" zone piekt. Toon een korte hint ("praat even; zet zo dat de balk groen is").
- **Microfoonkeuze** als er meerdere invoerbronnen zijn (`enumerateDevices`).

**AGC + spraak-DSP (ASR-kwaliteit is leidend)**
- **AGC-toggle, standaard AAN.** Implementeer via de `getUserMedia`-constraint
  `autoGainControl: true`. Als AGC aan staat, maak dan duidelijk dat de handmatige
  gevoeligheidsknop een fijnafstemming is (de browser regelt het niveau al mee); je kunt de
  handmatige gain dan subtieler laten meewegen of de slider visueel dempen.
- **Spraakgerichte voorbewerking, standaard AAN, als toggles:**
  - `echoCancellation: true` en `noiseSuppression: true` als `getUserMedia`-constraints —
    dit is de door de browser getunede, lichte ruis-/echo-onderdrukking. Voor gesprekken in
    een ruimte pakt dit stemmen goed uit de omgeving zonder de stem te beschadigen.
  - Optioneel een lichte **hoogdoorlaatfilter** (`BiquadFilterNode`, ~80 Hz) tegen
    laagfrequente brom/rommel. Houd het licht; geen smalle bandpass die de stem dof maakt.
  - Optioneel een instelbare **noise-gate** (drempel) om stiltes/ruis weg te laten vallen.
- **Belangrijke waarschuwing voor de bouwer (in code/README documenteren):** pas géén
  agressieve spectrale denoising (bijv. zware RNNoise-instellingen) standaard toe op de
  audio die geüpload wordt — sterk denoisen introduceert artefacten die de WER van Canary
  verslechteren. De veilige default is: **browser-AGC + lichte noiseSuppression + hoogdoorlaat**.
  Zwaardere DSP alleen achter een expliciete, niet-standaard toggle, met een waarschuwing.
- **VAD (optioneel, aanbevolen):** voeg voice-activity-detection toe (bijv. Silero-VAD via
  WASM) om lange stiltes te trimmen. Dit verkleint de upload en verwerkingstijd zonder de
  ASR-kwaliteit te schaden — beter dan spectraal denoisen. Zet dit als aparte toggle.
- Alle toggles/instellingen alleen client-side onthouden (localStorage), nooit server-side
  (anonimiteit).

**Opslaan + uploaden**
- **Tegelijk lokaal opslaan én uploaden:** tijdens/aan het einde van de opname wordt
  het bestand geüpload naar de transcriptieserver **en** kan de gebruiker het lokaal
  downloaden (blob → downloadknop). Gebruik zo mogelijk **chunked upload** tijdens de
  opname zodat lange sessies robuust zijn.
- Duidelijke opname-status (opnemen / gepauzeerd / geüpload), met de VU-meter zichtbaar
  tijdens het opnemen.

### 3. Upload van bestaand bestand
- Accepteer gangbare audioformaten (wav, mp3, m4a, ogg, webm, flac). Server
  transcodeert waar nodig (ffmpeg).
- Toon uploadvoortgang en een maximum bestandsgrootte/lengte (zie open vragen).

### 4. Sessie & later ophalen
- Elke upload/opname krijgt een **onvoorspelbaar sessie-ID** (bijv. hoge-entropie
  token). Dit ID is de enige sleutel tot het resultaat — behandel het als een geheim.
- Na uploaden kan de gebruiker **kiezen**:
  - **Wachten** op de transcriptie (live statuspagina die pollt of via SSE/websocket
    update), of
  - het **sessie-ID kopiëren** en later terugkomen om het resultaat op te halen.
- Een "ophalen"-veld waar men het sessie-ID plakt om transcript + verslag te downloaden.
- Toon altijd zichtbaar wanneer de data **automatisch verwijderd** wordt.

### 5. Prompts / verslag genereren
- Na (of naast) de ruwe transcriptie kan de gebruiker een **verslag laten uitwerken**.
- De uitgeschreven prompt-teksten staan in **`PROMPTS.md`** (gedeelde basis-instructie +
  zes secties + gecombineerd "Volledig verslag"). Gebruik die letterlijk.
- Bied **standaard-prompts** aan, minimaal:
  - **Samenvatting**
  - **Verslag** (uitgewerkt gespreksverslag)
  - **Actiepunten**
  - **Afspraken**
  - **Besluiten**
  - **Aandachtspunten**
  - (combineerbaar: bijv. "verslag met samenvatting + actiepunten + besluiten")
- Bied ook een **eigen prompt** aan (vrij tekstveld) dat op het transcript wordt
  toegepast.
- De LLM-stap draait als aparte job op de queue (na de STT-stap) via het OpenAI-
  compatibele endpoint. Resultaat wordt bij de sessie bewaard tot de bewaartermijn.
- Toon transcript en verslag naast elkaar; beide te kopiëren/downloaden (txt/markdown).

### 6. Bewaartermijn & opschonen
- **Alles wat bij een sessie hoort** (audio, transcript, verslag, metadata) wordt
  **automatisch verwijderd 2 werkdagen ná het moment dat de verwerking klaar is** — niet
  vanaf de upload. De gebruiker mag dus wachten op het transcript; het venster van 2
  werkdagen om via de code terug te komen begint pas als het transcript beschikbaar is.
- **Audio én transcript blijven allebei** die 2 werkdagen bewaard (audio niet eerder
  weggooien) zodat de gebruiker beide alsnog kan ophalen.
- Weekenden tellen niet mee: klaar op vrijdag → verloopt dinsdag, niet zondag.
- Implementeer dit met een **geplande opschoontaak** (aparte cron-container of
  scheduler in de app) die verlopen sessies hard verwijdert (bestanden + DB-rijen).
- Sla per sessie een `expires_at` op dat **werkdag-bewust** is berekend en pas dit gezet
  wordt zodra de verwerking is afgerond.

## Niet-functionele eisen
- **Privacy by design:** geen tracking, geen analytics naar derden, geen
  persoonsgegevens, minimale logging (geen transcript-inhoud in logs).
- **Schaalbaarheid:** de STT- en LLM-verwerking staat op de queue, los van de webrequest.
  Meer volume = meer workers. De VM-opzet moet één-op-één opschaalbaar zijn naar meer
  worker-containers, en later naar een aparte GPU-node.
- **Robuustheid:** jobs met retry/backoff; nette foutmeldingen naar de gebruiker;
  idempotente verwerking per sessie.
- **Configuratie via env-vars:** modelnamen, endpoints, bewaartermijn, maxgrootte.

## Deliverables
1. `docker-compose.yml` met services: `web` (frontend), `api` (FastAPI), `redis`,
   `worker` (STT + LLM, GPU-toegang), `db` (Postgres), en een `cleanup`-scheduler.
   Reverse proxy (Caddy/nginx) optioneel voor TLS.
2. Frontend met de drie schermen: opnemen/uploaden, wachten/statuspagina,
   ophalen-via-sessie-ID.
3. Backend-API: endpoints voor upload (incl. chunked), status pollen, transcript/verslag
   ophalen, verslag-prompt starten.
4. Worker met STT-pipeline (ffmpeg → faster-whisper) en LLM-pipeline (prompt → verslag).
5. `.env.example`, een **README** met setup-/deploy-instructies, en een korte notitie
   over de privacy-/bewaarkeuzes.
6. Basale tests voor de API en de werkdag-bewuste `expires_at`-berekening.

## Aanpak
- Begin met een werkende dunne verticale slice: upload → job → Whisper → transcript
  tonen. Daarna recorder, dan verslag-prompts, dan opschonen/bewaartermijn.
- Houd het simpel; voeg geen features toe die niet in deze prompt staan zonder overleg.
- Stel verhelderende vragen bij ambiguïteit in plaats van aannames te stapelen.
