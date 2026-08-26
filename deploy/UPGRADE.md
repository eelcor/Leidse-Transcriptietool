# Upgraden van een bestaande deployment

Voor een **bestaande** prod-installatie die je wilt bijwerken naar de laatste `main`.
(Een verse installatie doe je met [`deploy/install.sh`](install.sh); zie [`DEPLOY.md`](DEPLOY.md).)

## De snelste weg: `deploy/update.sh`
Vanuit de repo-root op de prod-machine:
```bash
./deploy/update.sh              # pull -> rebuild -> recreate -> verifiëren
# ./deploy/update.sh -y         # zonder bevestigingsvragen (CI)
# ./deploy/update.sh archief.tgz  # update vanuit een tar-archief (i.p.v. git)
```
Het script: haalt `main` op (fast-forward), **herbouwt de images**, recreëert de containers, en checkt
`/api/config`, de gemounte woordenlijsten en of STT op de GPU draait. Het bouwt de **diarize**-image
alleen mee als `DIARIZE_BACKEND=pyannote` in `.env` staat, en **waarschuwt** bij een Blackwell-GPU
zonder cu128-STT-libs.

## Waarom een rebuild nodig is (belangrijk)
De backend-**code zit in de images**. De dev-bind-mounts (`docker-compose.override.yml`) zijn
**gitignored** en staan dus niet op prod. Daarom brengt `git pull` alleen deze dingen live:

| Verandert met alleen `git pull` (bind-mount) | Vereist een **image-rebuild** |
|---|---|
| frontend (`./frontend`), docs, `PROMPTS.md`, `glossaries/` | api, worker (endpoints, STT, prompts, worker-logica) |

Een `docker compose restart` laadt nieuwe **code** niet en pakt **nieuwe mounts** niet op — gebruik
`docker compose up -d` (recreate), zoals `update.sh` doet.

## Handmatig (wat `update.sh` doet)
```bash
git pull --ff-only
# Blackwell (RTX PRO 6000, compute 12.0): zet eenmalig in .env (anders CPU-fallback):
#   STT_CUBLAS_SPEC=nvidia-cublas-cu12>=12.8,<12.9
#   STT_CUDNN_SPEC=nvidia-cudnn-cu12>=9.7
#   STT_CUDA_RUNTIME_SPEC=nvidia-cuda-runtime-cu12>=12.8,<12.9
docker compose build           # + '--profile diarize' als diarisatie aanstaat
docker compose up -d           # recreate
```

## Migraties
**Geen.** Deze release is migratie-vrij: geen nieuwe kolommen op bestaande tabellen. Progressvoortgang
loopt via Redis (efemeer), woordenlijst/sjabloon via bestaande JSON-/tekstvelden. Een bestaande DB
werkt zonder ingrepen.

## Verifiëren na de upgrade
```bash
docker compose logs worker | grep -i "val terug op CPU"   # LEEG = STT draait op de GPU
curl -sk https://<prod-host>/api/glossaries | head         # lijsten terug = glossaries gemount
```
En functioneel: start een **korte opname** → de **progressbalk** hoort mee te lopen en het **verslag**
komt door **zonder `APITimeoutError`**. Laat gebruikers **hard verversen** (Ctrl/Cmd+Shift+R) voor de
nieuwe frontend.

## Twee dingen om vooraf te checken
1. **LLM en `enable_thinking`.** De verslag-timeout-fix stuurt `chat_template_kwargs.enable_thinking=false`
   mee. Dat werkt met **llama.cpp + `--jinja`**. Draait je Qwen via een andere laag (LiteLLM-proxy,
   vLLM, externe API) die dat veld **afwijst**, dan faalt verslag-generatie. Oplossing: reasoning
   serverseitig uitzetten, óf `LLM_ENABLE_THINKING=true` (stuurt een leeg `extra_body`) **en**
   `LLM_TIMEOUT_SECONDS` ruim zetten.
2. **Blackwell-STT** vereist de **cu128**-libs (zie hierboven). De driver (CUDA 13) is ruim genoeg;
   de cu128-libs zijn de enige variabele. De `"val terug op CPU"`-check is je bevestiging.

## Terugrollen
```bash
git log --oneline -5          # kies de vorige commit
git checkout <vorige-commit>
docker compose build && docker compose up -d
```
De data (DB/volumes) blijft staan; alleen code/images gaan terug. (Migratie-vrij, dus veilig.)
