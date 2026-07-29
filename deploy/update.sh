#!/usr/bin/env bash
# =============================================================================
# Update de transcriptietool naar een nieuwere versie.
#
#   ./deploy/update.sh                 # haalt de nieuwste code (git) en herbouwt
#   ./deploy/update.sh <archief.tgz>   # update vanuit een tar-archief
#
# Draait de nieuwe images en start de stack opnieuw. Volumes (audio, database,
# model-cache) blijven behouden.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

c() { printf '\033[1;36m%s\033[0m\n' "$*"; }

if [ "${1:-}" != "" ] && [ -f "${1:-}" ]; then
  c "==> Uitpakken van ${1}"
  tar xzf "$1"
elif [ -d .git ]; then
  c "==> Nieuwste code ophalen (git pull)"
  git pull --ff-only
else
  c "Geen git-repo en geen archief opgegeven. Pak zelf een nieuwe versie uit en draai opnieuw."
  exit 1
fi

c "==> Images herbouwen"
docker compose build
c "==> Stack opnieuw starten (volumes blijven behouden)"
docker compose up -d
# LET OP: PROMPTS.md en de Caddyfile zijn als LOSSE bestanden gemount. Een edit vervangt
# de inode, en `docker compose restart` herlaadt die NIET — de oude inode blijft in de
# draaiende container gemount. Alleen een RECREATE re-resolvet de bind-mount. Daarom
# force-recreate voor de config-dragende services (web=Caddyfile, api/worker=PROMPTS.md).
# De frontend/ is een MAP-mount en is sowieso al live zonder recreate.
c "==> Config-services opnieuw aanmaken (prompt/Caddy zeker geladen)"
docker compose up -d --force-recreate web api worker
docker compose ps

cat <<'NOTE'

Klaar. Let op:
- Bij een release met DATABASE-wijzigingen staan de benodigde stappen in de
  release-notes (deze versie gebruikt geen automatische migraties). Nieuwe TABELLEN
  worden bij de start automatisch aangemaakt; nieuwe KOLOMMEN op bestaande tabellen
  vereisen een 'ALTER TABLE' zoals vermeld bij de release.
- De worker downloadt een eventueel nieuw STT-model bij de eerste start opnieuw.
NOTE
