#!/usr/bin/env bash
# Prepara la lettura di Trovaprezzi con Chrome su questo PC:
# apre il profilo Chrome dedicato al tracker (accetta i cookie, poi chiudi la finestra)
# e attiva chrome=auto in tracker.conf.
#
#   scripts/setup-chrome.sh                              # cerca Chrome da solo
#   scripts/setup-chrome.sh "flatpak run com.google.Chrome"   # oppure indica il comando
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/conf.sh

setting="${1:-auto}"
TRACKER_CHROME="$setting" python3 browser.py --setup
conf_set chrome "$setting"
echo "Attivato: chrome=$setting in tracker.conf. Prova con:  FORCE=1 scripts/run-local.sh"
