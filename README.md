# Leidse Transcriptietool

Laagdrempelige, **anonieme** webapp (geen login) waarmee collega's audio laten
transcriberen en er optioneel een verslag van laten maken. Privacy en
anonimiteit staan voorop; daarna laagdrempeligheid, kwaliteit van Nederlandse
transcriptie en schaalbaarheid.

## Waarom deze tool?

- We zoeken een **laagdrempelige manier waarop álle collega's betrouwbare en
  vertrouwelijke AI** kunnen gebruiken voor transcriptie en verslagen.
- We wachten al een tijd op **TINA** (gemeente Leeuwarden) en hopen dat die ooit als
  open source vrijkomt. Tot die tijd moet dit mensen eenvoudig helpen om gesprekken —
  óók vertrouwelijke — goed te transcriberen en om te zetten naar functionele verslagen.
- In Leiden zit nu **~10% van de medewerkers in ons AI-netwerk**. Met deze tool hopen
  we de overige **90%** ook verantwoord gebruik te laten maken van AI, voor iets waar
  bijna iedereen behoefte aan heeft.
- We ontwikkelen er niet superhard aan, maar we zorgen dat het **zo veilig mogelijk** is.

> ⚠️ **Belangrijk om te weten**
> - **Draai dit binnen je interne netwerk.** Niet zomaar open op het publieke internet zetten.
> - **De tool is niet perfect.** Lees de [handleiding](docs/handleiding.html) en de
>   [quick reference card](docs/quickref.html). **Maak altijd zelf aantekeningen** en
>   **bewaar de audio** — die optie zit er niet voor niets in.
> - **Nog niet beschermd tegen prompt injectie** (via de inhoud van een transcript of een
>   eigen prompt). Mogelijk een toekomstige feature — houd daar rekening mee bij
>   vertrouwelijk of extern materiaal.

- **STT:** **faster-whisper** (large-v2), NVIDIA **Canary 1B v2** (via NeMo), óf een
  extern **OpenAI-compatibel `/v1/audio/transcriptions`-endpoint** (`openai`) — zodat je
  STT net als de LLM kunt offloaden. Schakelbaar via `STT_BACKEND`, achter één interface.
- **Verslag-LLM:** hergebruikt het **bestaande, OpenAI-compatibele Qwen3.6-27b
  endpoint** (er wordt geen nieuwe LLM gehost).
- **Bewaartermijn:** alles wordt automatisch verwijderd **2 werkdagen ná de
  verwerking** (weekenden tellen niet mee).

## Documentatie

- **Gebruikershandleiding:** [`docs/handleiding.html`](docs/handleiding.html) — stap-voor-stap met screenshots.
- **Quick reference card:** [`docs/quickref.html`](docs/quickref.html) — één pagina, printbaar.
- **Deploy-handleiding (prod):** [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

> **Eerste start:** de worker downloadt bij de eerste run automatisch het STT-model
> (faster-whisper large-v2 ~1,5 GB, of Canary ~2 GB) naar een cache-volume. Internet
> is dan eenmalig nodig; daarna draait het offline.

## Architectuur

```
  Browser (vanilla SPA)
    │  opnemen (MediaRecorder+WebAudio) / uploaden
    ▼
  web  (Caddy: static + reverse proxy)
    │  /api
    ▼
  api  (FastAPI) ──enqueue──►  redis  ──►  worker (arq)
    │                                        │  ffmpeg → STT (Canary/Whisper)
    ▼                                        │  → transcript (+timestamps)
  db  (Postgres: sessies/jobs/verslagen)     │  LLM-verslag via Qwen-endpoint
                                             ▼
  cleanup (scheduler)  ── verwijdert sessies na expires_at (werkdag-bewust)
```

De **wachtrij** ontkoppelt de webrequest van de zware verwerking. Dit is de
schaalbaarheids-as: `--scale worker=N` of later een aparte GPU-node.

## Snel starten (Docker Compose)

Vereist: Docker + Docker Compose. Voor GPU-transcriptie ook de
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

```bash
cp .env.example .env
#  Pas in .env minimaal aan:
#   - LLM_BASE_URL  -> jouw bestaande Qwen-endpoint
#   - STT_DEVICE    -> cpu (dev) of cuda (prod)
#   - STT_BACKEND   -> faster_whisper (start) of canary

docker compose up -d --build
# open http://localhost:8080
```

**Pure CPU-run (geen GPU):** zet `STT_DEVICE=cpu` en comment het `deploy:`-GPU-blok
van de `worker` in `docker-compose.yml` uit.

**Canary/NeMo aanzetten:** zet `STT_BACKEND=canary`, `STT_MODEL=nvidia/canary-1b-v2`
en bouw de worker met `INSTALL_NEMO=1` (in `docker-compose.yml` onder `worker.build.args`,
of `docker compose build --build-arg INSTALL_NEMO=1 worker`). NeMo vereist een
CUDA-passende `torch`.

> **End-to-end getest** (nemo_toolkit 2.7.3). De backend handelt automatisch af:
> (1) canary-1b-v2 laadt als `EncDecMultiTaskModel` (de generieke
> `ASRModel.from_pretrained` kan die abstracte klasse niet instantiëren);
> (2) het model laadt altijd eerst op CPU (`map_location='cpu'`) en gaat daarna
> — optioneel in fp16 via `STT_COMPUTE_TYPE=float16` — naar de GPU, zodat het
> op een GPU met weinig vrije ruimte niet al tijdens het laden OOM knalt;
> (3) bij `STT_DEVICE=cpu` worden de GPU's verborgen (`CUDA_VISIBLE_DEVICES=""`)
> vóór torch laadt, anders laadt NeMo's interne timestamps-model alsnog op een
> GPU en krijg je CUDA OOM naast Qwen.
>
> **GPU-architectuur (belangrijk voor oudere kaarten):** NeMo trekt standaard de
> nieuwste torch (CUDA 13) mee, en **CUDA 13 ondersteunt Volta (Tesla V100,
> sm_70) niet meer** → `CUDA error: no kernel image available`. Draai je op V100
> of ouder, installeer dan expliciet een **torch met CUDA 12.x** (bevat nog sm_70),
> bijv. `pip install torch==2.6.0+cu124 --index-url https://download.pytorch.org/whl/cu124`
> (voldoet aan NeMo's `torch>=2.6.0`). Nieuwere kaarten (RTX Pro 6000 = sm_120)
> werken wél met de cu13-default.
>
> **Prestatie (getest op V100, fp16):** modellaadtijd ~43s (eenmalig bij
> worker-startup), daarna ~0,74s per transcriptie van 7s audio (~10× realtime);
> op CPU ~2,1s (~3,5× realtime). De laadtijd is eenmalig, niet per job.

## GPU- & resource-afwegingen

- **Dev:** de 4×V100 zijn bezet door Qwen; voor STT is alleen een Quadro P1000
  (4GB) beschikbaar. Draai daarom op dev met `STT_DEVICE=cpu` + `STT_COMPUTE_TYPE=int8`
  (werkende CPU-fallback), of faster-whisper op de P1000 met int8.
- **Prod:** de RTX Pro 6000 draait Qwen met ~10GB vrij. Canary past erin, maar
  deelt de kaart. Daarom `STT_CONCURRENCY=1` (default): maximaal één STT-job
  tegelijk, zodat piek-VRAM voorspelbaar blijft en Qwen niet uit het geheugen
  wordt gedrukt. De wachtrij vangt pieken op.
- De **verslag-LLM** kost in dit project geen extra VRAM: het is het bestaande endpoint.

## Configuratie

Alles via env-vars — zie [`.env.example`](.env.example). Belangrijkste:

| Var | Betekenis |
|---|---|
| `STT_BACKEND` | `faster_whisper` of `canary` |
| `STT_MODEL` | `large-v2` (whisper) / `nvidia/canary-1b-v2` |
| `STT_DEVICE` / `STT_COMPUTE_TYPE` | `cpu`+`int8` (dev) of `cuda`+`float16` (prod) |
| `STT_CONCURRENCY` | max gelijktijdige STT-jobs (VRAM-bescherming) |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | bestaand Qwen-endpoint |
| `RETENTION_WORKDAYS` | bewaartermijn in werkdagen (default 2) |
| `MAX_UPLOAD_MB` | max uploadgrootte (default 200) |

## Ontwikkelen & testen

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=. pytest            # API-tests (SQLite) + werkdag-berekening
```

De tests draaien zonder Redis/GPU: SQLite + een nep-queue.

## API (kort)

| Methode | Pad | Doel |
|---|---|---|
| POST | `/api/sessions` | sessie aanmaken (chunked upload) |
| PUT | `/api/sessions/{id}/audio` | audio-chunk toevoegen |
| POST | `/api/sessions/{id}/complete` | upload afronden → job |
| POST | `/api/upload` | single-shot bestand-upload |
| GET | `/api/sessions/{id}/status` | status pollen |
| GET | `/api/sessions/{id}/events` | live status via SSE |
| GET | `/api/sessions/{id}` | transcript + verslagen |
| POST | `/api/sessions/{id}/reports` | verslag genereren |
| GET | `/api/sessions/{id}/transcript.txt` | transcript downloaden |
| GET | `/api/sessions/{id}/reports/{rid}.md` | verslag downloaden |

## Privacy- & bewaarkeuzes (belangrijk)

- **Anoniem:** geen login, geen cookies-muur, geen accounts. De **sessie-code**
  (256-bits token) is de enige sleutel tot de data en wordt als geheim behandeld.
  Wie de code kwijt is, kan er niet meer bij — dat is opzet.
- **Geen persoonsgegevens** in de database; **geen tracking/analytics** naar derden.
- **Minimale logging:** transcript-inhoud wordt nooit gelogd.
- **Client-side voorkeuren:** recorder-instellingen staan in `localStorage`, nooit
  op de server.
- **Automatische verwijdering:** `expires_at` wordt **werkdag-bewust** gezet zodra
  de verwerking klaar is (niet bij upload) — dus het venster van 2 werkdagen begint
  pas als het transcript beschikbaar is. Audio én transcript blijven die periode
  bewaard zodat de gebruiker beide kan ophalen. De `cleanup`-service verwijdert
  daarna bestanden én DB-rijen hard. Weekenden tellen niet mee (klaar op vrijdag →
  verloopt dinsdag). Feestdagen zijn bewust niet meegenomen (uitbreidbaar in
  `app/workdays.py`).

## Isolatie & security

Elke sessie is volledig geïsoleerd; er lekt geen data tussen gebruikers. Geverifieerd
met een concurrency-test (meerdere gelijktijdige uploads met verschillende teksten en
een eigen prompt) plus negatieve checks:

- **Onvoorspelbare sleutel:** de sessie-code is een 256-bits token; onbekende/geraden
  codes geven `404`.
- **Geen enumeratie:** er is geen endpoint dat sessies opsomt (`GET /api/sessions` → 405).
- **Per-sessie opslag & queries:** bestanden staan onder de sessie-id; report-endpoints
  matchen op zowel sessie- als report-id.
- **Geen path traversal:** endpoints doen eerst de DB-lookup (onbekende id → 404); de
  reverse proxy normaliseert `../` naar de SPA-fallback (geen bestandsuitlever).
- **Geen XSS:** verslagen worden als Markdown gerenderd met een eigen renderer die alle
  HTML escaped.
- **Concurrency:** STT is begrensd (`STT_CONCURRENCY`), LLM-verslagen draaien parallel;
  elke job werkt uitsluitend op zijn eigen sessie/rij (geen gedeelde mutable state).

## Audio-kwaliteit (waarom zo)

De veilige default aan de opnamekant is **browser-AGC + lichte noiseSuppression +
hoogdoorlaat (~80 Hz)**. **Geen** agressieve spectrale denoising: dat introduceert
artefacten die de WER van Canary verslechteren. Server-side wordt alleen naar
16 kHz mono geresampled (ffmpeg). Optionele VAD (stiltes trimmen) verkleint de
upload zonder de ASR-kwaliteit te schaden.

## Opschalen

- Meer volume: `docker compose up -d --scale worker=3`.
- Later: worker(s) naar een aparte GPU-node; alleen `REDIS_URL`/`DATABASE_URL`
  hoeven te wijzen naar de gedeelde Redis/Postgres. De rest blijft gelijk.
