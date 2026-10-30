# Tracker prezzi

Ogni giorno uno dei PC accesi esegue `tracker.py`, che legge su Amazon.it e MediaWorld i prezzi
dei prodotti elencati in `PRODUCTS`:

- **Scheda video**: Radeon RX 9070 XT nuova
- **Mini PC server**: GMKtec K8 Plus, Beelink SER8, GEEKOM A8 Max, GMKtec M7 Ultra, NiPoGi AM06 Pro
  (solo configurazioni da 32 GB, niente barebone o ricondizionati)

Per ogni prodotto i risultati vanno in `docs/data/<id>/`:

- `offers.json`: le offerte dell'ultima rilevazione, dalla più economica
- `history.json`: una riga per giorno (minimo, media delle 10 più economiche, minimo per negozio)

`docs/data/products.json` è l'elenco dei prodotti per la dashboard e `docs/data/status.json`
la data dell'ultima rilevazione riuscita.

La dashboard (`docs/index.html`) è pubblicata con GitHub Pages e legge quei file, con una
scheda per gruppo (scheda video, mini PC).

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

## Aggiungere o cambiare un prodotto

In `tracker.py`, `PRODUCTS` ha una voce per prodotto: le ricerche da fare nei negozi
(`amazon`, `mediaworld`), le espressioni che il titolo deve contenere (`match`, tutte) o non deve
contenere (`exclude`), il prezzo minimo plausibile e il prezzo obiettivo (`target`).
Un prodotto nuovo compare da solo nella dashboard dopo la prima rilevazione.
Per provarne uno solo: `python3 tracker.py gmktec-k8-plus`.

Se un prodotto oggi non ha offerte valide, restano i dati del giorno prima; l'esecuzione
fallisce (e il timer riprova) solo se nessun prodotto è stato aggiornato.

## Aggiungere un negozio

Scrivi in `tracker.py` una funzione che riceve il testo da cercare e restituisce una lista di
`{"model", "shop", "price", "url"}`, aggiungila a `SHOPS` e metti la ricerca nei prodotti. Se un negozio
blocca la lettura, gli altri vengono salvati comunque; se falliscono tutti,
l'esecuzione termina con errore e il timer riprova all'ora successiva.

Trovaprezzi, Idealo e Kelkoo non sono usati: bloccano i lettori automatici con un captcha.
