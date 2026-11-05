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

## Configurazione locale (`tracker.conf`)

Le due funzioni facoltative qui sotto si configurano in `tracker.conf`, un file locale escluso
da git (contiene il topic ntfy, che non deve finire nel repo pubblico). Senza questo file il
tracker funziona come prima: solo Amazon e MediaWorld, nessuna notifica.

```
ntfy_topic=prezzi-...      # notifiche sul telefono
chrome=auto                # legge anche Trovaprezzi con Chrome (oppure il comando di Chrome)
```

### Notifiche sul telefono (ntfy)

Il tracker manda una notifica con [ntfy](https://ntfy.sh) quando il prezzo minimo di un prodotto:

- scende sotto il suo obiettivo (`target`): la prima volta, e poi solo se scende ancora;
- tocca un nuovo minimo storico.

Toccando la notifica si apre l'offerta; il pulsante *Dashboard* apre questa pagina.
Lo stesso avviso non viene ripetuto nello stesso giorno allo stesso prezzo (anche con `FORCE=1`).

```bash
scripts/setup-ntfy.sh            # primo PC: genera un topic casuale
scripts/setup-ntfy.sh <topic>    # altri PC: usa lo stesso topic
```

Sul telefono installa l'app ntfy e iscriviti al topic che lo script stampa; lo script poi
manda una notifica di prova (`python3 tracker.py --test-notify` la rimanda quando vuoi).
Su ntfy.sh i topic non hanno password: chi conosce il nome può leggerli, per questo il topic
sta solo in `tracker.conf`. Il workflow manuale lo legge dal segreto `NTFY_TOPIC` del repo.

### Trovaprezzi con Chrome

Trovaprezzi blocca i lettori automatici semplici. Con `chrome=auto` il tracker apre le sue
pagine in un Chrome vero (finestra normale, non headless) con un **profilo dedicato**, legge i
prezzi dai dati strutturati della pagina e richiude Chrome. Tra una pagina e l'altra aspetta
8-20 secondi. Il profilo dedicato serve perché da Chrome 136 il profilo principale non si può
comandare da programma; non tocca le tue schede né le tue sessioni.

```bash
scripts/setup-chrome.sh          # apre il profilo su Trovaprezzi: accetta i cookie e chiudi
FORCE=1 scripts/run-local.sh     # prova subito
```

- Se Trovaprezzi chiede una verifica, arriva una notifica ntfy e il tracker aspetta 4 minuti
  che tu la risolva nella finestra di Chrome; se no salta Trovaprezzi per quel giro.
- Serve un desktop attivo: dal timer systemd funziona dopo il login grafico.
- L'ultima pagina letta per ogni prodotto resta in `debug/` (escluso da git), utile se la
  lettura smette di funzionare.
- Chrome viene comandato con il protocollo DevTools da `browser.py`, solo libreria standard.

Nota: è comunque una lettura automatica, anche se fatta con un browser vero; le condizioni
d'uso di Trovaprezzi non la prevedono. Il volume è minimo (una pagina per prodotto al giorno).

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

Idealo e Kelkoo non sono usati: bloccano i lettori automatici con un captcha. Trovaprezzi
si legge solo con Chrome (vedi sopra).
