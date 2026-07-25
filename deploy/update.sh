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
docker compose ps

cat <<'NOTE'

Klaar. Let op:
- Bij een release met DATABASE-wijzigingen staan de benodigde stappen in de
  release-notes (deze versie gebruikt geen automatische migraties). Nieuwe TABELLEN
  worden bij de start automatisch aangemaakt; nieuwe KOLOMMEN op bestaande tabellen
  vereisen een 'ALTER TABLE' zoals vermeld bij de release.
- De worker downloadt een eventueel nieuw STT-model bij de eerste start opnieuw.
NOTE
