#!/usr/bin/env bash
# =============================================================================
# Update de transcriptietool naar een nieuwere versie.
#
#   ./deploy/update.sh                 # haalt de nieuwste code (git) en herbouwt
#   ./deploy/update.sh <archief.tgz>   # update vanuit een tar-archief
#   ./deploy/update.sh -y [...]        # zonder bevestigingsvragen (CI)
#
# Herbouwt de images (de backend-code zit IN de images; de dev-bind-mounts zijn
# gitignored en staan niet op prod) en recreëert de stack. Volumes (audio,
# database, model-cache) blijven behouden. Zie deploy/UPGRADE.md.
# =============================================================================
set -euo pipefail

YES=0; [ "${1:-}" = "-y" ] && { YES=1; shift; }
cd "$(dirname "$0")/.."

c()    { printf '\033[1;36m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
ask()  { [ "$YES" = 1 ] && return 0; read -r -p "$1 [y/N] " a; [ "$a" = "y" ] || [ "$a" = "Y" ]; }

# --- 1) Nieuwe versie binnenhalen (archief of git) ---
if [ "${1:-}" != "" ] && [ -f "${1:-}" ]; then
  c "==> Uitpakken van ${1}"
  tar xzf "$1"
elif [ -d .git ]; then
  c "==> Nieuwste code ophalen (git pull)"
  [ -n "$(git status --porcelain)" ] && warn "   Er zijn lokale wijzigingen; de pull kan conflicteren."
  git pull --ff-only
  echo "   nu op $(git rev-parse --short HEAD)"
else
  c "Geen git-repo en geen archief opgegeven. Pak zelf een nieuwe versie uit en draai opnieuw."
  exit 1
fi

# --- 2) Blackwell-check: STT-CUDA-libs op cu128 voor sm_120 (anders CPU-fallback) ---
if command -v nvidia-smi >/dev/null 2>&1; then
  cap=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
  capmaj=${cap%%.*}
  if [ -n "$capmaj" ] && [ "$capmaj" -ge 10 ] 2>/dev/null && ! grep -q '^STT_CUBLAS_SPEC=' .env 2>/dev/null; then
    warn "   GPU compute $cap (Blackwell) zonder STT_CUBLAS_SPEC in .env -> faster-whisper valt op CPU terug."
    warn "   Zet in .env (zie deploy/DEPLOY.md) en draai opnieuw:"
    warn "     STT_CUBLAS_SPEC=nvidia-cublas-cu12>=12.8,<12.9"
    warn "     STT_CUDNN_SPEC=nvidia-cudnn-cu12>=9.7"
    warn "     STT_CUDA_RUNTIME_SPEC=nvidia-cuda-runtime-cu12>=12.8,<12.9"
    ask "   Toch doorgaan met de build (zonder cu128)?" || { echo "Afgebroken."; exit 1; }
  fi
fi

# --- 3) Diarisatie (opt-in) alleen meebouwen als die aanstaat ---
profiles=""
if grep -qE '^DIARIZE_BACKEND=pyannote' .env 2>/dev/null; then
  profiles="--profile diarize"; c "   diarisatie actief -> diarize-image wordt meegebouwd"
fi

c "==> Images herbouwen (backend-code + STT-CUDA)"
docker compose $profiles build

c "==> Stack recreëren (volumes blijven behouden)"
docker compose $profiles up -d

# --- 4) Verificatie ---
c "==> Verifiëren…"
for _ in $(seq 1 30); do
  [ "$(docker compose ps api --format '{{.State}}' 2>/dev/null)" = "running" ] && break; sleep 2
done
docker compose exec -T api python -c "import urllib.request,json;d=json.load(urllib.request.urlopen('http://localhost:8000/api/config'));print('   api OK — STT=%s  LLM=%s'%(d.get('stt_label'),d.get('llm_model')))" 2>/dev/null \
  || warn "   Kon /api/config niet lezen — check: docker compose logs api"
g=$(docker compose exec -T api sh -c 'ls /glossaries/*.txt 2>/dev/null | wc -l' 2>/dev/null | tr -d '[:space:]')
echo "   woordenlijsten gemount: ${g:-0}"
if docker compose logs worker 2>&1 | grep -qi "val terug op CPU"; then
  warn "   WAARSCHUWING: STT viel terug op CPU (Blackwell? -> cu128-libs, zie DEPLOY.md)."
else
  echo "   geen CPU-fallback in de worker-log."
fi
echo
c "Klaar."
echo "Laat gebruikers hard verversen (Ctrl/Cmd+Shift+R). Test een korte opname: progressbalk +"
echo "verslag zonder timeout. Details/rollback: deploy/UPGRADE.md."
