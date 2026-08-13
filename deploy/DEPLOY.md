# Deploy-handleiding (productie)

Deze map bevat alles om de anonieme transcriptie-webapp op een productiemachine
te zetten. De snelste weg is het `install.sh`-script; hieronder ook de handmatige
stappen en de belangrijke productie-aandachtspunten.

## Inhoud van het pakket

```
docker-compose.yml     # de volledige stack (web/api/worker/db/redis/cleanup)
Caddyfile              # reverse proxy + HTTPS (domein/TLS via env)
.env.example           # alle instelbare env-vars
backend/               # FastAPI api + arq worker (STT + LLM) + cleanup
frontend/              # statische SPA (recorder, upload, ophalen)
PROMPTS.md             # letterlijke verslag-prompts (single source of truth)
deploy/install.sh      # geleide installatie
deploy/DEPLOY.md       # dit bestand
deploy/package.sh      # maakt een distribueerbaar tar-archief
```

## Vereisten op de prod-machine

- **Docker** + **Docker Compose v2**.
- **NVIDIA GPU** met drivers (voor GPU-STT). Plus container-GPU-toegang via **CDI**
  (aanbevolen) of de nvidia-runtime. Check: `docker info | grep -i cdi` moet
  `nvidia.com/gpu=...` tonen. Zo niet:
  ```bash
  sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml   # geen daemon-restart nodig
  ```
- Een bereikbaar **OpenAI-compatibel LLM-endpoint** — je eigen LLM-laag. Op prod bijv.
  een **LiteLLM-proxy** (die naar je model/provider routeert), of vLLM/Ollama/llama.cpp/
  een externe API. Er wordt géén LLM in dit pakket gehost; je wijst er via `LLM_BASE_URL`
  naartoe.

## Snelste weg: install.sh

```bash
./deploy/install.sh
```
Het script:
1. checkt docker/compose en detecteert de GPU;
2. kiest automatisch de juiste **torch-variant** (zie hieronder);
3. vraagt domein, TLS, LLM-endpoint en poorten uit;
4. schrijft `.env`, bouwt de images en start de stack;
5. wacht op de API-health.

Non-interactief kan ook: zet de env-vars en draai `./deploy/install.sh -y`.

## GPU-architectuur — LET OP (torch-variant)

De worker-image bevat torch, en de torch-build moet bij de GPU passen:

| GPU | compute cap | `TORCH_VARIANT` |
|---|---|---|
| **RTX Pro 6000** (Blackwell) | 12.0 (sm_120) | `default` (CUDA 13) |
| Hopper (H100) / Ada (L40/4090) / Ampere / Turing | 9.0 / 8.9 / 8.x / 7.5 | `default` |
| **Tesla V100** (Volta) | 7.0 (sm_70) | `cu124` — CUDA 13 laat Volta vallen! |

`install.sh` detecteert dit. Handmatig: zet `TORCH_VARIANT` in `.env`. Verkeerde
keuze geeft `CUDA error: no kernel image available` (arch niet ondersteund).

Voor **prod (RTX Pro 6000)** is `TORCH_VARIANT=default` correct.

## GPU-geheugen (headroom) — belangrijk bij gedeelde kaarten

Er zijn TWEE VRAM-pieken, en de tweede is de lastigste:
1. **Laden**: Canary + intern timestamps-model in fp32 → **~6-7 GB**.
2. **Inferentie**: attention/activations **groeien met de audiolengte** — bij langere
   opnames een piek van **~8-9 GB in één allocatie**. Dit is meestal wat OOM veroorzaakt,
   niet het laden.

Deelt de STT-GPU met een groot LLM (zoals Qwen met 256K-context, waarvan het geheugen
fluctueert), reken dan op **ruim voldoende vrije VRAM** — richtlijn **≥12 GB vrij** voor
langere bestanden, niet krap 7-10 GB. Te weinig marge geeft `CUDA out of memory` (tijdens
laden óf inferentie); een mislukte poging kan VRAM vasthouden (herstart de worker om vrij
te geven). **Let op:** dit VRAM-verhaal geldt voor **Canary** (zwaar). De **standaard
faster-whisper** (large-v2, ~4 GB in float16) is veel lichter en draait prima op een
gedeelde kaart — op de dev-V100 (gedeeld met Qwen) draait de STT gewoon op de GPU.

- Genoeg vrije VRAM (bv. prod-RTX): `STT_DEVICE=cuda`, `STT_COMPUTE_TYPE=float16`.
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` staat al gezet (beperkt fragmentatie).
- Krappe/gedeelde kaart zonder marge: twee opties:
  - **STT op CPU** (`STT_DEVICE=cpu`, `STT_COMPUTE_TYPE=float32`) — betrouwbaar
    (~2s/clip warm), raakt de andere GPU-modellen niet, mét timestamps.
  - **GPU zonder timestamps** (`STT_DEVICE=cuda`, `STT_COMPUTE_TYPE=float16`,
    `STT_WORD_TIMESTAMPS=false`) — de backend slaat dan Canary's interne
    timestamps-model over, waardoor alleen het hoofdmodel (~2GB fp16) op de GPU past.
    Snel (~0,7s/clip), maar zonder woord/segment-timestamps.

## STT via een extern endpoint (`STT_BACKEND=openai`)

Wil je STT niet in de worker draaien maar op een aparte server (net als de LLM)? Zet
`STT_BACKEND=openai`. De worker POST't dan de audio naar een **OpenAI-compatibel
`/v1/audio/transcriptions`-endpoint** en heeft zelf **geen STT-model, torch of GPU** nodig
(alleen ffmpeg). Zet dan ook `INSTALL_NEMO=0`.

- **Endpoint-opties:** whisper.cpp-server (`whisper-server`), of een faster-whisper
  OpenAI-wrapper (`faster-whisper-server` / `speaches`).
- **Config:** `STT_OPENAI_BASE_URL` (bv. `http://host.docker.internal:8035/v1`),
  `STT_OPENAI_API_KEY`, en `STT_MODEL` = de modelnaam die dat endpoint verwacht (bv. `whisper-1`).
- De backend probeert `verbose_json` (met segment-timestamps) en valt terug op `json`
  (alleen tekst) als de server dat formaat niet ondersteunt.

## Handmatige installatie

```bash
cp .env.example .env
# Pas minimaal aan:
#   SITE_ADDRESS       -> jouw domein (bv. transcriptie.example.nl)
#   CADDY_TLS          -> e-mailadres (Let's Encrypt) of "internal"
#   LLM_BASE_URL       -> jouw OpenAI-compat. LLM (bv. LiteLLM-proxy)
#   TORCH_VARIANT      -> default (RTX) of cu124 (V100)
#   WORKER_GPU_DEVICE  -> nvidia.com/gpu=0  (of =all)
#   STT_DEVICE         -> cuda
#   WEB_HTTP_PORT/WEB_HTTPS_PORT -> zie "reverse proxy" hieronder

docker compose build
docker compose up -d
docker compose logs -f worker    # eerste start: STT-model (faster-whisper large-v2 ~1,5 GB,
                                 # of Canary ~2 GB) wordt gedownload
```

## HTTPS & domein

- `SITE_ADDRESS=transcriptie.example.nl` + `CADDY_TLS=jij@example.nl` → Caddy haalt
  automatisch een Let's Encrypt-certificaat (poort 80 + 443 moeten publiek bereikbaar
  zijn en DNS moet naar de host wijzen).
- `CADDY_TLS=internal` → self-signed lokale CA (dev/intern; browserwaarschuwing, maar
  wél een https secure context — nodig voor de in-browser recorder / microfoon).

## Geen browserwaarschuwing (certificaat)

De waarschuwing komt doordat `CADDY_TLS=internal` een self-signed certificaat gebruikt.
Drie manieren om ervan af te komen:

1. **Eigen certificaat (aanbevolen voor intern) — geen client-config.**
   Gebruik een certificaat dat je clients al vertrouwen: één van je **interne CA**
   (in veel organisaties via AD/GPO uitgerold) of een **publiek certificaat** voor een
   echt (sub)domein. Leg `cert.pem` (fullchain) en `key.pem` in `./certs/` en zet:
   ```
   SITE_ADDRESS=transcriptie.jouwdomein.nl
   CADDY_TLS=/certs/cert.pem /certs/key.pem
   ```
   Op **beheerde apparaten** die de uitgevende CA al vertrouwen: nul waarschuwingen,
   niets te installeren.

2. **Publiek domein + Let's Encrypt** (`CADDY_TLS=jij@domein.nl`). Zero-config en
   globaal vertrouwd, maar poort 80/443 moeten publiek bereikbaar zijn (of gebruik een
   DNS-01-challenge voor een intern-only host).

3. **De interne CA vertrouwen op de clients** (bij `CADDY_TLS=internal`). De app serveert
   Caddy's root-CA automatisch op **`/caddy-root.crt`** (bijv. `https://<host>/caddy-root.crt`),
   en toont onderin de pagina een subtiel linkje **"Certificaatwaarschuwing? Installeer ons
   certificaat"** — dat linkje verschijnt alleen als er zo'n interne CA is. Gebruikers
   downloaden 'm daar; centraal uitrollen kan ook (haal 'm op met
   `docker compose cp web:/data/caddy/pki/authorities/local/root.crt caddy-root.crt`).
   Installeer 'm in de trust-store van de clients (handmatig, of centraal via GPO/MDM):
   - **Windows:** dubbelklik → *Install Certificate* → *Local Machine* → *Trusted Root Certification Authorities*.
   - **macOS:** open in Keychain Access → *System* → dubbelklik → *Always Trust*.
   - **Linux:** kopieer naar `/usr/local/share/ca-certificates/` → `sudo update-ca-certificates`.
   - **Firefox** (eigen store): Instellingen → Certificaten → Importeren → "vertrouw voor websites".
   Herstart daarna de browser. Let op: dit maakt álle door die Caddy-CA uitgegeven certificaten vertrouwd.

## Naast een bestaande reverse proxy (bv. een Caddy die al draait)

Draait er al een Caddy/nginx op **80/443**? Laat de app die poorten dan niet óók pakken.
Twee nette manieren:

### Aanbevolen: app-Caddy lokaal, jouw bestaande Caddy ervoor

De meegeleverde `web`-Caddy doet alle routing al goed (frontend, `/api`, `/docs`,
`/caddy-root.crt`, SSE). Laat 'm alléén op localhost luisteren; jouw bestaande Caddy doet de
publieke TLS en proxyt ernaartoe. Zo hoef je niets aan de routing over te doen.

In `.env`:
```
WEB_BIND=127.0.0.1:                 # let op de dubbele punt aan het eind → alleen lokaal
WEB_HTTP_PORT=8080
WEB_HTTPS_PORT=8443
SITE_ADDRESS=transcriptie.example.nl
CADDY_TLS=internal                  # interne self-signed; de front-Caddy doet de publieke TLS
DEFAULT_SNI=transcriptie.example.nl
```
In je **bestaande** Caddyfile (die 80/443 al bezit) één siteblok erbij:
```
transcriptie.example.nl {
    reverse_proxy https://127.0.0.1:8443 {
        transport http {
            tls_insecure_skip_verify                   # interne self-signed cert overslaan
        }
        flush_interval -1                              # houdt SSE/live-status realtime
        header_up Host {host}                          # app-Caddy matcht op Host; {host} = hostnaam zonder poort
    }
}
```
`docker compose up -d`, `caddy reload` bij je bestaande Caddy — klaar. De `tls_insecure_skip_verify`
geldt alleen voor de interne hop naar localhost; publiek heb je een echt certificaat via je
bestaande Caddy. De `header_up Host {host}` is defensief: de app-Caddy kiest zijn siteblok op de
**Host-header**, dus die moet gelijk zijn aan `SITE_ADDRESS`. Bij een front op poort 443 met dezelfde
hostnaam klopt dat vanzelf; deze regel houdt het ook goed als de front op een afwijkende poort draait
(anders zou de poort in de Host meelopen en niets matchen — end-to-end getest).

### Alternatief: geen tweede Caddy, direct naar de api

Publiceer de api lokaal en laat de bestaande proxy alles doorzetten. In een compose-override
(`docker compose -f docker-compose.yml -f jouw-override.yml up -d`):
```yaml
services:
  api:
    ports: ["127.0.0.1:8000:8000"]
    environment: { SERVE_FRONTEND: /app/frontend }   # api serveert dan ook de frontend
    volumes: ["./frontend:/app/frontend:ro"]
  web:
    profiles: ["disabled"]                            # web-container niet starten
```
In je bestaande Caddy:
```
transcriptie.example.nl {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```
Nadeel: `/docs` (handleiding) serveer je dan zelf (bv. vanuit `./docs`); de eerste manier heeft dat
al ingebouwd.

> **Uploads achter een front-proxy.** Bestanden én opnames worden in **chunks van 4 MB**
> geüpload (met automatische retry), dus je hoeft géén 200 MB-bodylimiet in te stellen —
> maar zorg dat de front-proxy per request minstens ~4 MB toestaat en niet te snel
> time-out. Let vooral op **nginx** (`client_max_body_size` staat standaard op **1 MB** →
> zet 'm op bv. `10m`) en op tunnels/CDN's met een strakke bodylimiet. `/api/*` moet met
> ruime read-timeouts worden doorgezet (bij een lange opname zijn er veel chunk-PUTs).

### Onder een subpad (bijv. `https://example.nl/transcriptie/`)

De frontend gebruikt **relatieve paden** (afgeleid van waar de app geladen wordt), dus de app
werkt onder elk subpad **zonder configuratie of patch-script** — mits je front-proxy het
subpad-prefix **strip't** vóór hij doorzet. In je bestaande Caddy:
```
example.nl {
    redir /transcriptie /transcriptie/          # forceer de afsluitende slash
    handle_path /transcriptie/* {                # handle_path STRIP't het /transcriptie-prefix
        reverse_proxy https://127.0.0.1:8443 {
            transport http { tls_insecure_skip_verify }
            flush_interval -1
            header_up Host {host}
        }
    }
}
```
De app-Caddy krijgt dan gewoon `/api/*`, `/css/*`, enz. (prefix eraf); de browser blijft
`/transcriptie/...` gebruiken. Werkt ook op de web-root (zonder subpad) — dan is er niets te doen.
Voor **nginx**: gebruik `location /transcriptie/ { proxy_pass https://127.0.0.1:8443/; }` (let op
de afsluitende slash achter de upstream — die strip't het prefix), plus een redirect van
`/transcriptie` naar `/transcriptie/`.

## LLM-endpoint bereikbaar maken vanuit de container

- LLM op een **andere host**: gebruik dat adres direct in `LLM_BASE_URL`.
- LLM op **dezelfde host** als Docker: gebruik `http://host.docker.internal:PORT/v1`
  (de compose zet hiervoor `extra_hosts: host-gateway`). `.local`/mDNS-namen werken
  meestal NIET in containers — gebruik een IP of echte DNS-naam.

## Verifiëren

```bash
docker compose ps
docker compose exec worker nvidia-smi -L        # ziet de worker de GPU?
curl -k https://SITE_ADDRESS/api/health         # {"status":"ok"}
```

## Opschalen

```bash
docker compose up -d --scale worker=3           # meer STT/LLM-doorvoer
```
STT-concurrency per worker staat op 1 (`STT_CONCURRENCY`) om piek-VRAM te beperken.

## Automatisch starten bij boot (systemd-service)

De containers draaien met `restart: unless-stopped`, dus na een reboot komen ze
sowieso terug (mits de Docker-daemon op boot start). Voor **expliciete controle**
(`systemctl start/stop/status`) en de garantie dat `docker compose up -d` ook draait
wanneer de stack ooit met `compose down` is platgelegd, is er een kant-en-klare unit:
[`deploy/transcribe.service`](transcribe.service).

Installeren (pas `User`/`Group` en `WorkingDirectory` in de unit aan als je pad/account
anders is; de gebruiker moet in de `docker`-group zitten):

```bash
sudo cp deploy/transcribe.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now transcribe.service    # nu starten én bij boot
systemctl status transcribe.service
```

Beheer daarna:

```bash
sudo systemctl stop transcribe.service      # docker compose down
sudo systemctl start transcribe.service     # docker compose up -d
sudo systemctl restart transcribe.service   # herstart de stack
```

De unit is `Type=oneshot` met `RemainAfterExit=yes`: `up -d` start de containers en de
service blijft "active", zodat `stop` netjes `docker compose down` aanroept. Na een
update (`./deploy/update.sh`) hoef je de unit niet te herstarten — dat script beheert de
containers zelf; de unit bepaalt alleen het gedrag bij boot en handmatig start/stop.

### Ook het LLM-endpoint bij boot starten

De app **host geen LLM**; hij praat met een bestaand OpenAI-compatibel endpoint
(`LLM_BASE_URL`). Draait dat endpoint op dezelfde host (bv. een `llama-server`/vLLM/LiteLLM-
proces), dan moet dát óók automatisch terugkomen na een reboot — anders staan verslagen na
een herstart eindeloos in de wachtrij. Draai het als **user-systemd-service** met *linger*
aan (dan start het bij boot, zónder sudo of ingelogde sessie):

```bash
loginctl enable-linger "$USER"                 # user-services starten bij boot
systemctl --user daemon-reload
systemctl --user enable --now qwen-llm.service  # jouw LLM-server-unit
systemctl --user status qwen-llm.service
```

Een user-unit staat in `~/.config/systemd/user/<naam>.service` met een simpel
`ExecStart=<jouw start-commando>`, `Restart=on-failure` en `WantedBy=default.target`.
Controleer na een test-reboot dat zowel het endpoint (`curl $LLM_BASE_URL/models`) als de
stack (`docker compose ps`) vanzelf draaien.

## Updaten

Gebruik het update-script (volumes blijven behouden):

```bash
./deploy/update.sh                 # git pull + herbouwen + herstarten
./deploy/update.sh nieuwe.tgz      # of update vanuit een tar-archief
```

Nieuwe **tabellen** worden bij de start automatisch aangemaakt (via `create_all`).
Voegt een release **kolommen** toe op bestaande tabellen, voer dan de `ALTER TABLE`
uit de release-notes uit — deze versie gebruikt nog geen automatische migraties
(Alembic staat op de roadmap: issue #2). Voorbeeld voor deze release:

```sql
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source varchar(12);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS audio_format varchar(16);
-- de tabel stat_events wordt automatisch aangemaakt
```

## Data & privacy

Audio/transcript/verslag staan in het `audiodata`-volume en in Postgres, en worden
automatisch verwijderd **2 werkdagen na de verwerking** (weekend telt niet mee) door
de `cleanup`-service. Geen persoonsgegevens, geen tracking, minimale logging.
