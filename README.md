# Tracker prezzi RX 9070 XT

Ogni giorno uno dei PC accesi esegue `tracker.py`, che legge i prezzi della Radeon RX 9070 XT nuova
su Amazon.it e MediaWorld e salva i risultati in `docs/data/`:

- `offers.json`: le offerte dell'ultima rilevazione, dalla più economica
- `history.json`: una riga per giorno (minimo, media delle 10 più economiche, minimo per negozio)

La dashboard (`docs/index.html`) è pubblicata con GitHub Pages e legge quei file.

## Esecuzione dai PC

Amazon e MediaWorld bloccano i server di GitHub (anche con un browser headless),
quindi la rilevazione parte dai PC di casa. `scripts/run-local.sh` scarica i dati dal repo:
se oggi un PC ha già fatto la rilevazione non fa nulla, altrimenti rileva i prezzi e li carica.

Su Fedora un timer systemd dell'utente lo avvia 3 minuti dopo l'accensione e poi ogni ora
(recupera anche le esecuzioni perse a PC spento):

```bash
scripts/install-fedora.sh
```

Log e stato:

```bash
journalctl --user -u price-tracker -n 30
```

Per forzare una nuova rilevazione oggi: `FORCE=1 scripts/run-local.sh`.

Il workflow GitHub **Rileva prezzi** resta solo per l'avvio manuale.

Nessuna dipendenza: basta Python 3.9 o successivo.

## Aggiungere un negozio

Scrivi in `tracker.py` una funzione che restituisce una lista di
`{"model", "shop", "price", "url"}` e aggiungila a `SOURCES`. Se un negozio
blocca la lettura, gli altri vengono salvati comunque; se falliscono tutti,
l'esecuzione termina con errore e il timer riprova all'ora successiva.

Trovaprezzi, Idealo e Kelkoo non sono usati: bloccano i lettori automatici con un captcha.
