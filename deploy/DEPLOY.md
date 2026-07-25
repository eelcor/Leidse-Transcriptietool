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
- Een bereikbaar **OpenAI-compatibel LLM-endpoint** (het bestaande Qwen). Er wordt
  géén LLM in dit pakket gehost.

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
te geven). **Op de dev-V100 (16 GB, gedeeld met Qwen) is dit niet werkbaar → daar draait
STT op CPU.** Voor betrouwbare GPU-STT: een GPU die niet met een groot LLM gedeeld wordt,
of ruime vrije VRAM.

- Genoeg vrije VRAM (bv. prod-RTX): `STT_DEVICE=cuda`, `STT_COMPUTE_TYPE=float16`.
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` staat al gezet (beperkt fragmentatie).
- Krappe/gedeelde kaart zonder marge: twee opties:
  - **STT op CPU** (`STT_DEVICE=cpu`, `STT_COMPUTE_TYPE=float32`) — betrouwbaar
    (~2s/clip warm), raakt de andere GPU-modellen niet, mét timestamps.
  - **GPU zonder timestamps** (`STT_DEVICE=cuda`, `STT_COMPUTE_TYPE=float16`,
    `STT_WORD_TIMESTAMPS=false`) — de backend slaat dan Canary's interne
    timestamps-model over, waardoor alleen het hoofdmodel (~2GB fp16) op de GPU past.
    Snel (~0,7s/clip), maar zonder woord/segment-timestamps.

## Handmatige installatie

```bash
cp .env.example .env
# Pas minimaal aan:
#   SITE_ADDRESS       -> jouw domein (bv. transcriptie.example.nl)
#   CADDY_TLS          -> e-mailadres (Let's Encrypt) of "internal"
#   LLM_BASE_URL       -> jouw Qwen-endpoint
#   TORCH_VARIANT      -> default (RTX) of cu124 (V100)
#   WORKER_GPU_DEVICE  -> nvidia.com/gpu=0  (of =all)
#   STT_DEVICE         -> cuda
#   WEB_HTTP_PORT/WEB_HTTPS_PORT -> zie "reverse proxy" hieronder

docker compose build
docker compose up -d
docker compose logs -f worker    # eerste start: Canary-model (~2GB) wordt gedownload
```

## HTTPS & domein

- `SITE_ADDRESS=transcriptie.example.nl` + `CADDY_TLS=jij@example.nl` → Caddy haalt
  automatisch een Let's Encrypt-certificaat (poort 80 + 443 moeten publiek bereikbaar
  zijn en DNS moet naar de host wijzen).
- `CADDY_TLS=internal` → self-signed lokale CA (dev/intern; browserwaarschuwing, maar
  wél een https secure context — nodig voor de in-browser recorder / microfoon).

## Naast een bestaande reverse proxy (bv. OpenWebUI's Caddy)

Draait er al iets op poort 80/443? Twee opties:

1. **Andere poorten** voor de meegeleverde Caddy:
   ```
   WEB_HTTP_PORT=8080
   WEB_HTTPS_PORT=8443
   ```
   Site draait dan op `https://domein:8443`.

2. **Bestaande proxy laten proxien** naar de app (geen dubbele Caddy):
   - Laat de `web`-service weg of publiceer geen poorten, en zet de bestaande proxy
     zo dat hij `/` en `/api/*` naar de `api`-container (poort 8000) stuurt. Zorg dat
     de proxy in hetzelfde docker-netwerk zit, of publiceer de api-poort lokaal:
     ```yaml
     # in een compose override:
     api:
       ports: ["127.0.0.1:8000:8000"]
     ```
   - In je bestaande Caddy:
     ```
     transcriptie.example.nl {
         reverse_proxy /api/* 127.0.0.1:8000 { flush_interval -1 }
         # frontend statisch serveren of ook naar api proxien
     }
     ```

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

## Updaten

```bash
git pull   # of pak een nieuw tar-archief uit
docker compose build
docker compose up -d
```

## Data & privacy

Audio/transcript/verslag staan in het `audiodata`-volume en in Postgres, en worden
automatisch verwijderd **2 werkdagen na de verwerking** (weekend telt niet mee) door
de `cleanup`-service. Geen persoonsgegevens, geen tracking, minimale logging.
