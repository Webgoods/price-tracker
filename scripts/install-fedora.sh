#!/usr/bin/env bash
# Installa il timer systemd dell'utente che avvia run-local.sh.
set -euo pipefail
dir="$HOME/.config/systemd/user"
mkdir -p "$dir"
cp "$(dirname "$0")"/systemd/price-tracker.{service,timer} "$dir/"
systemctl --user daemon-reload
systemctl --user enable --now price-tracker.timer
systemctl --user list-timers price-tracker.timer --no-pager
