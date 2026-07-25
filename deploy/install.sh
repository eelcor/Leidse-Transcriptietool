#!/usr/bin/env bash
# =============================================================================
# Anonieme transcriptie-webapp — installer
#
# Detecteert de GPU, kiest de juiste torch-build, vraagt de omgeving uit,
# schrijft .env, bouwt de images en start de stack.
#
# Gebruik:
#   ./deploy/install.sh                 # interactief
#   ENV_VAR=... ./deploy/install.sh -y  # non-interactief (alle waarden via env)
#
# Belangrijke env-vars (allemaal optioneel; anders wordt ernaar gevraagd):
#   SITE_ADDRESS LLM_BASE_URL LLM_MODEL LLM_API_KEY CADDY_TLS
#   WORKER_GPU_DEVICE TORCH_VARIANT STT_DEVICE STT_COMPUTE_TYPE
#   WEB_HTTP_PORT WEB_HTTPS_PORT
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."   # repo-root
YES=0; [ "${1:-}" = "-y" ] && YES=1

c() { printf '\033[1;36m%s\033[0m\n' "$*"; }      # info
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }   # waarschuwing
die() { printf '\033[1;31mFOUT: %s\033[0m\n' "$*" >&2; exit 1; }

ask() { # ask VAR "vraag" "default"
  local var=$1 prompt=$2 def=${3:-} cur=${!1:-}
  if [ -n "$cur" ]; then eval "$var=\$cur"; return; fi          # env override
  if [ "$YES" = 1 ]; then eval "$var=\$def"; return; fi
  local ans; read -r -p "$prompt [${def}]: " ans || true
  eval "$var=\"\${ans:-\$def}\""
}

# --- 1) Prerequisites -------------------------------------------------------
c "==> Prerequisites controleren"
command -v docker >/dev/null || die "docker niet gevonden."
docker compose version >/dev/null 2>&1 || die "docker compose (v2) niet gevonden."
docker info >/dev/null 2>&1 || die "kan geen verbinding maken met de docker-daemon."

# --- 2) GPU detecteren ------------------------------------------------------
c "==> GPU detecteren"
GPU_MODE=cpu; DETECTED_TORCH=default; DETECTED_DEVICE="nvidia.com/gpu=all"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  nvidia-smi -L | sed 's/^/   /'
  cap=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
  case "$cap" in
    7.0|7.2) DETECTED_TORCH=cu124; warn "   Volta (compute $cap, bv. Tesla V100): torch cu124 nodig (cu13 laat sm_70 vallen)." ;;
    "")      warn "   compute capability onbekend; TORCH_VARIANT=default aangehouden." ;;
    *)       c "   compute capability $cap -> TORCH_VARIANT=default." ;;
  esac
  # Container-GPU-toegang: CDI of nvidia-runtime?
  if docker info 2>/dev/null | grep -q 'nvidia.com/gpu'; then
    GPU_MODE=cdi; c "   GPU-in-container via CDI beschikbaar."
  elif docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; then
    GPU_MODE=runtime
    warn "   Alleen nvidia-runtime (geen CDI). De compose gebruikt CDI-devices;"
    warn "   genereer CDI met: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
    warn "   (geen daemon-restart nodig) — of pas de worker-service aan (zie DEPLOY.md)."
  else
    GPU_MODE=none
    warn "   GPU-drivers gevonden, maar geen container-GPU-toegang (CDI/runtime)."
    warn "   Installeer de NVIDIA Container Toolkit, of draai STT op CPU."
  fi
else
  warn "   Geen NVIDIA-GPU gevonden -> STT draait op CPU."
fi

# --- 3) Waarden uitvragen ---------------------------------------------------
c "==> Configuratie"
if [ "$GPU_MODE" = "cdi" ] || [ "$GPU_MODE" = "runtime" ]; then
  STT_DEVICE_DEF=cuda; STT_COMPUTE_DEF=float16
else
  STT_DEVICE_DEF=cpu;  STT_COMPUTE_DEF=int8; DETECTED_DEVICE=""
fi

ask SITE_ADDRESS       "Domein/host van de site (bv. transcriptie.example.nl)" "localhost"
ask CADDY_TLS          "TLS: e-mail voor Let's Encrypt, of 'internal' (self-signed dev)" "internal"
ask LLM_BASE_URL       "OpenAI-compatibel LLM-endpoint (Qwen)" "http://host.docker.internal:8033/v1"
ask LLM_MODEL          "LLM-modelnaam" "Qwen3.6-27B"
ask LLM_API_KEY        "LLM API key (of 'not-needed')" "not-needed"
ask TORCH_VARIANT      "torch-variant (default | cu124)" "$DETECTED_TORCH"
ask STT_DEVICE         "STT-device (cuda | cpu)" "$STT_DEVICE_DEF"
ask STT_COMPUTE_TYPE   "STT compute type (float16 | float32 | int8)" "$STT_COMPUTE_DEF"
ask WORKER_GPU_DEVICE  "GPU voor de worker (CDI, bv. nvidia.com/gpu=0 of =all)" "${DETECTED_DEVICE:-nvidia.com/gpu=all}"
ask WEB_HTTP_PORT      "HTTP-poort (verhoog als er al een proxy op 80 draait)" "80"
ask WEB_HTTPS_PORT     "HTTPS-poort (verhoog als er al een proxy op 443 draait)" "443"
# STT-engine: faster_whisper is robuust (klein/begrensd geheugen). Canary geeft
# topkwaliteit NL maar heeft een grote inferentie-piek (~8-9GB) -> een GPU die niet
# met een groot LLM gedeeld wordt, of veel vrije VRAM.
# "openai" offload't STT naar een extern OpenAI-compatibel endpoint (geen lokaal model/torch).
ask STT_BACKEND        "STT-engine (faster_whisper | canary | openai)" "faster_whisper"
case "$STT_BACKEND" in
  canary) STT_MODEL_DEF="nvidia/canary-1b-v2" ;;
  openai) STT_MODEL_DEF="whisper-1" ;;
  *)      STT_MODEL_DEF="large-v2" ;;
esac
ask STT_MODEL          "STT-model" "$STT_MODEL_DEF"
if [ "$STT_BACKEND" = "openai" ]; then
  ask STT_OPENAI_BASE_URL "Extern STT-endpoint (OpenAI-compatibel)" "http://host.docker.internal:8035/v1"
  ask STT_OPENAI_API_KEY  "STT API key (of 'not-needed')" "not-needed"
  STT_DEVICE=cpu; STT_COMPUTE_TYPE=int8   # niet relevant; model draait extern
fi

# --- 4) .env schrijven ------------------------------------------------------
c "==> .env schrijven"
[ -f .env ] && { cp .env ".env.bak.$(date +%s 2>/dev/null || echo old)" 2>/dev/null || true; warn "   bestaande .env geback-upt"; }
# default_sni = eerste hostnaam uit SITE_ADDRESS (voor toegang via IP, dat geen SNI stuurt).
DEFAULT_SNI=${DEFAULT_SNI:-${SITE_ADDRESS%% *}}
# NeMo/Canary alleen meebouwen als die engine gekozen is (scheelt anders een zware build).
INSTALL_NEMO=$([ "$STT_BACKEND" = "canary" ] && echo 1 || echo 0)
cat > .env <<EOF
# Gegenereerd door deploy/install.sh
INSTALL_NEMO=${INSTALL_NEMO}
TORCH_VARIANT=${TORCH_VARIANT}
WORKER_GPU_DEVICE=${WORKER_GPU_DEVICE}
SITE_ADDRESS=${SITE_ADDRESS}
CADDY_TLS=${CADDY_TLS}
DEFAULT_SNI=${DEFAULT_SNI}
WEB_HTTP_PORT=${WEB_HTTP_PORT}
WEB_HTTPS_PORT=${WEB_HTTPS_PORT}

DATABASE_URL=postgresql+asyncpg://transcribe:transcribe@db:5432/transcribe
REDIS_URL=redis://redis:6379/0
STORAGE_DIR=/data
MAX_UPLOAD_MB=200
DEFAULT_LANGUAGE=nl
RETENTION_WORKDAYS=2
CLEANUP_INTERVAL_SECONDS=3600

STT_BACKEND=${STT_BACKEND}
STT_MODEL=${STT_MODEL}
STT_DEVICE=${STT_DEVICE}
STT_COMPUTE_TYPE=${STT_COMPUTE_TYPE}
STT_CONCURRENCY=1
STT_WORD_TIMESTAMPS=true
STT_OPENAI_BASE_URL=${STT_OPENAI_BASE_URL:-http://host.docker.internal:8035/v1}
STT_OPENAI_API_KEY=${STT_OPENAI_API_KEY:-not-needed}
STT_OPENAI_TIMEOUT_SECONDS=600
AUDIO_OPTIMIZE_DEFAULT=true

LLM_BASE_URL=${LLM_BASE_URL}
LLM_MODEL=${LLM_MODEL}
LLM_API_KEY=${LLM_API_KEY}
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=600
PROMPTS_FILE=/app/PROMPTS.md
EOF
c "   .env klaar:"; sed 's/^/     /' .env

# --- 5) Bouwen & starten ----------------------------------------------------
if [ "$YES" != 1 ]; then read -r -p "Nu bouwen en starten? [Y/n]: " go || true; [ "${go:-Y}" = "n" ] && { c "Gestopt. Start later met: docker compose up -d --build"; exit 0; }; fi
if [ "$INSTALL_NEMO" = "1" ]; then c "==> Images bouwen (Canary/NeMo: kan lang duren, ~torch + NeMo download)";
else c "==> Images bouwen"; fi
docker compose build
c "==> Stack starten"
docker compose up -d

# --- 6) Health ---------------------------------------------------------------
c "==> Wachten op de API"
for i in $(seq 1 60); do
  if docker compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1; then
    c "   API is gezond."; break
  fi; sleep 2
done
c "==> Klaar. De worker downloadt bij de eerste start het Canary-model (~2GB)."
c "    Site:  https://${SITE_ADDRESS}${WEB_HTTPS_PORT:+:$([ "$WEB_HTTPS_PORT" = 443 ] && echo '' || echo $WEB_HTTPS_PORT)}"
c "    Logs:  docker compose logs -f worker"
