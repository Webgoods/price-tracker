#!/usr/bin/env bash
# Rileva i prezzi da questo PC e li carica sul repo, al massimo una volta al giorno.
# Lo avvia il timer systemd (vedi install-fedora.sh); si può lanciare anche a mano.
set -euo pipefail
cd "$(dirname "$0")/.."

today=$(TZ=Europe/Rome date +%F)
done_today() { grep -q "\"date\": \"$today\"" docs/data/history.json; }

# Già fatto oggi (da questo PC): non serve nemmeno la rete.
if done_today && [ "${FORCE:-}" != 1 ]; then echo "Rilevazione di $today già presente."; exit 0; fi

# Dopo l'accensione la rete può arrivare con qualche secondo di ritardo.
for i in $(seq 1 30); do
  git ls-remote -q origin HEAD >/dev/null 2>&1 && break
  [ "$i" = 30 ] && { echo "Rete non disponibile, riprovo al prossimo giro." >&2; exit 1; }
  sleep 10
done

git pull -q --rebase --autostash
# Un altro PC potrebbe averla già fatta.
if done_today && [ "${FORCE:-}" != 1 ]; then echo "Rilevazione di $today già fatta da un altro PC."; exit 0; fi

python3 tracker.py

git add docs/data
git diff --cached --quiet && exit 0
git commit -q -m "Prezzi del $today ($(hostname -s))" -- docs/data
for i in 1 2 3; do
  git push -q && { echo "Dati caricati."; exit 0; }
  git pull -q --rebase --autostash
done
echo "Push non riuscito." >&2; exit 1
