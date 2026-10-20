# Tracker prezzi RX 9070 XT

Ogni mattina GitHub Actions esegue `tracker.py`, che legge i prezzi della Radeon RX 9070 XT nuova
su Amazon.it e MediaWorld e salva i risultati in `docs/data/`:

- `offers.json`: le offerte dell'ultima rilevazione, dalla più economica
- `history.json`: una riga per giorno (minimo, media delle 10 più economiche, minimo per negozio)

La dashboard (`docs/index.html`) è pubblicata con GitHub Pages e legge quei file.

## Avvio manuale

Scheda **Actions** → **Rileva prezzi** → **Run workflow**. In locale:

```bash
python3 tracker.py
```

Nessuna dipendenza: basta Python 3.9 o successivo.

## Aggiungere un negozio

Scrivi in `tracker.py` una funzione che restituisce una lista di
`{"model", "shop", "price", "url"}` e aggiungila a `SOURCES`. Se un negozio
blocca la lettura, gli altri vengono salvati comunque; se falliscono tutti,
l'esecuzione termina con errore e GitHub ti manda un'email.

Trovaprezzi, Idealo e Kelkoo non sono usati: bloccano i lettori automatici con un captcha.
