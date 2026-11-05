#!/usr/bin/env bash
# Configura le notifiche ntfy su questo PC: scrive ntfy_topic in tracker.conf
# (escluso da git) con un topic casuale, a meno che non ne passi uno tu,
# e manda una notifica di prova.
#
#   scripts/setup-ntfy.sh                 # genera un topic nuovo
#   scripts/setup-ntfy.sh <topic>         # usa un topic esistente (es. sul secondo PC)
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/conf.sh

current=$(conf_get ntfy_topic)
if [ -n "$current" ] && [ -z "${1:-}" ]; then
  topic=$current
  echo "Topic già configurato in tracker.conf."
else
  topic="${1:-prezzi-$(python3 -c 'import secrets; print(secrets.token_hex(8))')}"
  conf_set ntfy_topic "$topic"
  echo "Salvato in tracker.conf."
fi

echo
echo "Sul telefono: app ntfy -> + -> iscriviti al topic:  $topic"
echo "(server predefinito ntfy.sh). Poi premi Invio per mandare una notifica di prova."
read -r _
python3 tracker.py --test-notify
