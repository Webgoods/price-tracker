#!/usr/bin/env bash
# Configura le notifiche ntfy su questo PC: crea ntfy.conf (escluso da git)
# con un topic casuale, a meno che non ne passi uno tu, e manda una notifica di prova.
#
#   scripts/setup-ntfy.sh                 # genera un topic nuovo
#   scripts/setup-ntfy.sh <topic>         # usa un topic esistente (es. sul secondo PC)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f ntfy.conf ] && [ -z "${1:-}" ]; then
  echo "ntfy.conf esiste già:"; grep -v '^#' ntfy.conf
else
  topic="${1:-prezzi-$(python3 -c 'import secrets; print(secrets.token_hex(8))')}"
  cat > ntfy.conf <<EOF
# Notifiche del tracker prezzi. File locale, escluso da git: non va nel repo pubblico.
topic=$topic
server=https://ntfy.sh
EOF
  chmod 600 ntfy.conf
  echo "Creato ntfy.conf con topic: $topic"
fi

topic=$(sed -n 's/^topic=//p' ntfy.conf)
echo
echo "Sul telefono: app ntfy -> + -> iscriviti al topic:  $topic"
echo "(server predefinito ntfy.sh). Poi premi Invio per mandare una notifica di prova."
read -r _
python3 tracker.py --test-notify
