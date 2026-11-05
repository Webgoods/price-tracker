# Funzioni per leggere e scrivere tracker.conf (chiave=valore), usate dagli script di setup.
CONF_FILE=tracker.conf

conf_get() { [ -f "$CONF_FILE" ] && sed -n "s/^$1=//p" "$CONF_FILE" | tail -1 || true; }

conf_set() {
  if [ ! -f "$CONF_FILE" ]; then
    printf '# Configurazione locale del tracker. Escluso da git: non va nel repo pubblico.\n' > "$CONF_FILE"
    chmod 600 "$CONF_FILE"
  fi
  if grep -q "^$1=" "$CONF_FILE"; then
    python3 - "$CONF_FILE" "$1" "$2" <<'PY'
import sys
path, key, value = sys.argv[1:]
lines = open(path).read().splitlines()
open(path, "w").write("\n".join(f"{key}={value}" if l.startswith(key + "=") else l for l in lines) + "\n")
PY
  else
    printf '%s=%s\n' "$1" "$2" >> "$CONF_FILE"
  fi
}
