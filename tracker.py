#!/usr/bin/env python3
"""Rileva i prezzi dei prodotti in PRODUCTS su alcuni negozi italiani.

Per ogni prodotto aggiorna docs/data/<id>/offers.json (offerte di oggi) e
docs/data/<id>/history.json (una riga per giorno). Scrive anche
docs/data/products.json (elenco per la dashboard) e docs/data/status.json
(data dell'ultima rilevazione riuscita, usata da run-local.sh).

Configurazione locale facoltativa in tracker.conf (escluso da git):
- ntfy_topic: manda una notifica quando un prodotto scende sotto il suo obiettivo
  o tocca un nuovo minimo storico (anche con la variabile NTFY_TOPIC);
- chrome: legge anche Trovaprezzi aprendo le pagine in un Chrome vero (browser.py).
Solo libreria standard: nessuna dipendenza.
"""
import html
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
DATA = ROOT / "docs" / "data"
CONF = ROOT / "tracker.conf"  # locale, escluso da git: il topic ntfy non va nel repo pubblico
DEBUG = ROOT / "debug"  # copie delle pagine lette col browser, per sistemare la lettura
DASHBOARD = "https://webgoods.github.io/price-tracker/"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
TOP_N = 10
PAUSE = 3  # secondi tra una richiesta e l'altra, per non farsi bloccare

USED = r"ricondizionat|usat[oa]|refurbished|rigenerat"
# Niente "cavo"/"supporto" qui: i titoli dei mini PC li citano spesso ("supporto VESA").
# Gli accessori li scarta già il prezzo minimo.
MINIPC_EXCLUDE = USED + r"|barebone|senza ram|senza ssd|no ram|no ssd"

# Ogni prodotto: le ricerche da fare nei negozi, le regole per riconoscere il
# modello giusto nel titolo (tutte le espressioni in "match" devono esserci,
# nessuna di "exclude") e il prezzo minimo sotto cui è un accessorio o un errore.
# "target" è il prezzo obiettivo mostrato nella dashboard.
PRODUCTS = [
    {
        "id": "rx9070xt", "group": "gpu", "name": "Radeon RX 9070 XT", "target": 750,
        "amazon": "radeon rx 9070 xt", "mediaworld": "rx 9070 xt",
        "trovaprezzi": "https://www.trovaprezzi.it/prezzo_schede-grafiche_amd_rx_9070_xt.aspx",
        "match": [r"9070\s*-?\s*XT"],
        "exclude": USED + r"|waterblock|water block|backplate|cavo|supporto|staffa|bracket|riser|"
                          r"pc gaming|pc desktop|computer|notebook",
        "min_price": 400,
    },
    {
        "id": "gmktec-k8-plus", "group": "minipc", "name": "GMKtec K8 Plus", "target": 600,
        "specs": "Ryzen 7 8845HS · 2× SO-DIMM DDR5 · 2× M.2 · 2× LAN 2.5G · OCuLink · Win 11 Pro",
        "amazon": "gmktec k8 plus 8845hs 32gb", "mediaworld": "gmktec k8 plus", "trovaprezzi": "gmktec k8 plus",
        "match": [r"gmktec", r"K8\s*Plus", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "beelink-ser8", "group": "minipc", "name": "Beelink SER8", "target": 600,
        "specs": "Ryzen 7 8845HS/8745HS · 2× SO-DIMM DDR5 · 2× M.2 · 1× LAN 2.5G · molto silenzioso · Win 11 Pro",
        "amazon": "beelink ser8 32gb", "mediaworld": "beelink ser8", "trovaprezzi": "beelink ser8",
        "match": [r"beelink", r"SER\s*8(?!\d)", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "geekom-a8-max", "group": "minipc", "name": "GEEKOM A8 Max", "target": 650,
        "specs": "Ryzen 7 8845HS/8745HS · 2× SO-DIMM DDR5 · 1× M.2 · 2× LAN 2.5G · garanzia 3 anni · Win 11 Pro",
        "amazon": "geekom a8 max", "mediaworld": "geekom a8 max", "trovaprezzi": "geekom a8 max",
        "match": [r"geekom", r"A8\s*Max", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "gmktec-m7-ultra", "group": "minipc", "name": "GMKtec M7 Ultra", "target": 520,
        "specs": "Ryzen 7 PRO 6850U · DDR5 dual channel · 2× M.2 · 2× LAN 2.5G Intel · OCuLink · Win 11 Pro",
        "amazon": "gmktec m7 ultra 32gb", "mediaworld": "gmktec m7", "trovaprezzi": "gmktec m7",
        "match": [r"gmktec", r"\bM7\b", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "nipogi-am06-pro", "group": "minipc", "name": "NiPoGi AM06 Pro", "target": 450,
        "specs": "Ryzen 7 7730U · 32 GB DDR4 espandibile · M.2 + slot 2,5\" · 2× LAN 1G · Win 11 Pro",
        "amazon": "nipogi am06 pro 32gb", "mediaworld": "nipogi am06 pro", "trovaprezzi": "nipogi am06 pro",
        "match": [r"AM06\s*Pro", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
]
GROUPS = {"gpu": "Scheda video", "minipc": "Mini PC server"}


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse_eur(text):
    """'1.049,76 €' -> 1049.76"""
    m = re.search(r"\d[\d.]*,\d{2}|\d+", text.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(0).replace(".", "").replace(",", "."))


def amazon(query):
    s = fetch("https://www.amazon.it/s?" + urllib.parse.urlencode({"k": query, "i": "computers"}))
    if "captcha" in s.lower() and "s-search-result" not in s:
        raise RuntimeError("captcha")
    return parse_amazon(s)


def parse_amazon(s):
    out = []
    for m in re.finditer(r'data-asin="(\w{10})"[^>]*data-component-type="s-search-result"', s):
        block = s[m.end():m.end() + 20000]
        nxt = block.find('data-component-type="s-search-result"')
        if nxt > 0:
            block = block[:nxt]
        t = re.search(r'<h2[^>]*aria-label="([^"]+)"', block) or \
            re.search(r"<h2.*?<span[^>]*>([^<]+)</span>", block, re.S)
        p = re.search(r'<span class="a-offscreen">([^<]+)</span>', block)
        if not (t and p):
            continue
        title = html.unescape(t.group(1)).replace("Annuncio sponsorizzato –", "").strip()
        out.append({"model": title, "shop": "Amazon.it", "price": parse_eur(html.unescape(p.group(1))),
                    "url": f"https://www.amazon.it/dp/{m.group(1)}"})
    return out


def mediaworld(query):
    s = fetch("https://www.mediaworld.it/it/search.html?" + urllib.parse.urlencode({"query": query},
                                                                                   quote_via=urllib.parse.quote))
    return parse_mediaworld(s)


def parse_mediaworld(s):
    out = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', s, re.S):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for el in (d.get("itemListElement") or []) if isinstance(d, dict) else []:
            item = el.get("item") or {}
            offer = item.get("offers") or {}
            if item.get("name") and offer.get("price"):
                # nome intero: dopo la virgola ci sono RAM e SSD, che servono al filtro
                out.append({"model": " ".join(item["name"].split()), "shop": "MediaWorld",
                            "price": float(offer["price"]), "url": item.get("url", "")})
    return out


SHOPS = {"Amazon.it": ("amazon", amazon), "MediaWorld": ("mediaworld", mediaworld)}


# ---------- Trovaprezzi, letto con un Chrome vero (browser.py) ----------

# Segni di una pagina di verifica vera. Non "datadome" né "challenge-platform": gli script
# antibot sono in tutte le pagine normali di Trovaprezzi e davano falsi allarmi.
CHALLENGE_WORDS = ("captcha-delivery.com", "cf-chl", "just a moment", "ci siamo quasi",
                   "attention required", "non sei un robot", "verifica di sicurezza",
                   "are you a robot", "access denied", "accesso negato")
CHALLENGE_WAIT = 240  # secondi per risolvere a mano una verifica nella finestra di Chrome


def trovaprezzi_url(query):
    if query.startswith("http"):
        return query
    return ("https://www.trovaprezzi.it/categoria.aspx?"
            + urllib.parse.urlencode({"libera": query, "id": -1, "sbox": "sb"}))


def _walk(node):
    if isinstance(node, list):
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v)


def _types(node):
    t = node.get("@type", [])
    return {t} if isinstance(t, str) else set(t)


def _text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_trovaprezzi_listing(s):
    """Offerte dalla lista delle pagine di ricerca (<li id="offer-...">): nome, negozio, totale."""
    out = []
    for block in re.split(r'<li id="offer-', s)[1:]:
        block = block.split("</li>", 1)[0] if "</li>" in block else block[:8000]
        name = re.search(r'class="item_name[^"]*"[^>]*>(.*?)</a>', block, re.S)
        shop = re.search(r'class="merchant_name"[^>]*>(.*?)</span>', block, re.S)
        total = re.search(r'class="item_total_price"[^>]*>(.*?)</div>', block, re.S) or \
            re.search(r'class="item_basic_price"[^>]*>(.*?)</div>', block, re.S)
        link = re.search(r'class="item_name[^"]*"[^>]*href="([^"]+)"', block) or re.search(r'href="(/goto/[^"]+)"', block)
        if not (name and total):
            continue
        price = parse_eur(_text(total.group(1)).replace("Tot.", ""))
        if not price:
            continue
        seller = _text(shop.group(1)) if shop else ""
        title = _text(name.group(1))
        out.append({"model": f"{title} — {seller}" if seller else title, "shop": "Trovaprezzi", "price": price,
                    "url": urllib.parse.urljoin("https://www.trovaprezzi.it/", html.unescape(link.group(1))) if link else ""})
    return out


def parse_trovaprezzi(s, page_url=""):
    """Offerte di una pagina Trovaprezzi: dalla lista delle offerte (pagine di ricerca e
    categoria, prezzo totale con spedizione) o, in mancanza, dai dati strutturati JSON-LD."""
    return parse_trovaprezzi_listing(s) or _trovaprezzi_jsonld(s, page_url)


def _trovaprezzi_jsonld(s, page_url=""):
    """Offerte dai dati strutturati (JSON-LD) della pagina: Product con Offer/AggregateOffer."""
    out = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', s, re.S):
        try:
            data = json.loads(html.unescape(m.group(1)))
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if "Product" not in _types(node) or not node.get("name"):
                continue
            offers = node.get("offers") or []
            offers = offers if isinstance(offers, list) else [offers]
            for offer in offers:
                inner = offer.get("offers") if isinstance(offer.get("offers"), list) else [offer]
                for o in inner:
                    price = o.get("price") or o.get("lowPrice")
                    if price is None:
                        continue
                    seller = (o.get("seller") or {}).get("name") if isinstance(o.get("seller"), dict) else None
                    if not seller and "AggregateOffer" in _types(o):
                        seller = f"{o.get('offerCount', 'più')} negozi"
                    title = " ".join(str(node["name"]).split())
                    out.append({"model": f"{title} — {seller}" if seller else title, "shop": "Trovaprezzi",
                                "price": float(str(price).replace(",", ".")),
                                "url": o.get("url") or node.get("url") or page_url})
    return out


def looks_like_challenge(s):
    if '<li id="offer-' in s:  # c'è la lista delle offerte: non è una verifica
        return False
    low = s.lower()
    return any(w in low for w in CHALLENGE_WORDS)


def main_category(s):
    """Link alla categoria principale di una pagina di ricerca senza offerte, se c'è."""
    i = s.find('class="most_popular"')
    m = re.search(r'<a class="relevant_item"[^>]*href="([^"]+)"', s[i:i + 3000]) if i >= 0 else None
    return urllib.parse.urljoin("https://www.trovaprezzi.it/", html.unescape(m.group(1))) if m else None


class BrowserSession:
    """Apre Chrome solo quando serve (alla prima pagina) e lo richiude alla fine."""

    def __init__(self, command):
        self.command, self.chrome, self.tab, self.pages = command, None, None, 0

    def trovaprezzi(self, query, product_id="pagina"):
        import browser  # solo qui: chi non usa Chrome non ne ha bisogno
        if self.chrome is None:
            self.chrome = browser.Chrome(self.command)
            self.tab = self.chrome.new_tab()
        elif self.pages:
            time.sleep(random.uniform(8, 20))  # ritmo da persona, non da robot
        self.pages += 1
        url = trovaprezzi_url(query)
        self.tab.goto(url)
        page = self.tab.html()
        offers = parse_trovaprezzi(page, url)
        if not offers and looks_like_challenge(page):
            warn("Trovaprezzi chiede una verifica",
                 f"Risolvila nella finestra di Chrome del tracker entro {CHALLENGE_WAIT // 60} minuti.")
            end = time.time() + CHALLENGE_WAIT
            while time.time() < end and not offers:
                time.sleep(5)
                page = self.tab.html()
                offers = parse_trovaprezzi(page, url)
                if not offers and not looks_like_challenge(page):
                    self.tab.goto(url)  # verifica superata: ricarico la pagina cercata
                    page = self.tab.html()
                    offers = parse_trovaprezzi(page, url)
                    break
            if not offers and looks_like_challenge(page):
                raise RuntimeError("verifica non risolta")
        category = main_category(page)
        if not offers and category:
            # pagina "scegli la categoria": apro quella principale proposta da Trovaprezzi
            time.sleep(random.uniform(3, 6))
            url = category
            self.tab.goto(url)
            page = self.tab.html()
            offers = parse_trovaprezzi(page, url)
        DEBUG.mkdir(exist_ok=True)
        (DEBUG / f"trovaprezzi-{product_id}.html").write_text(page)
        return offers

    def close(self):
        if self.chrome:
            self.chrome.close()


def browser_session():
    """Una BrowserSession se in tracker.conf c'è chrome=auto (o un comando), altrimenti None."""
    setting = local_settings().get("chrome", "")
    if not setting or setting in ("off", "0", "no"):
        return None
    import browser
    command = browser.find_chrome(setting)
    if not command:
        print("Chrome non trovato: Trovaprezzi saltato.", file=sys.stderr)
        return None
    return BrowserSession(command)


def keep(product, offer):
    """True se l'offerta è il prodotto giusto, nuovo e con un prezzo plausibile."""
    title = offer["model"]
    if not offer["price"] or offer["price"] < product["min_price"]:
        return False
    if not all(re.search(rx, title, re.I) for rx in product["match"]):
        return False
    return not re.search(product["exclude"], title, re.I)


def clean_offers(product, offers):
    seen, clean = set(), []
    for o in offers:
        if keep(product, o) and o["url"] not in seen:
            seen.add(o["url"])
            clean.append(o)
    clean.sort(key=lambda o: o["price"])
    return clean


def history_row(today, clean):
    by_shop = {}
    for o in clean:
        by_shop.setdefault(o["shop"], o["price"])
    return {
        "date": today,
        "min_price": clean[0]["price"],
        "avg_top10": round(statistics.mean(o["price"] for o in clean[:TOP_N]), 2),
        "offers": len(clean),
        "cheapest_model": clean[0]["model"],
        "cheapest_shop": clean[0]["shop"],
        "by_shop": by_shop,
        "source": "negozi",
    }


def save_product(product, clean, status, now, today):
    """Salva offerte e storico; restituisce lo storico dei giorni precedenti (per gli avvisi)."""
    folder = DATA / product["id"]
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{"rank": i + 1, **o} for i, o in enumerate(clean)]
    (folder / "offers.json").write_text(json.dumps(
        {"updated": now.isoformat(timespec="seconds"), "sources": status, "offers": rows},
        ensure_ascii=False, indent=1))

    hist_path = folder / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else []
    before = [h for h in history if h["date"] != today]
    history = sorted(before + [history_row(today, clean)], key=lambda h: h["date"])
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=1))
    return [h for h in before if h["date"] < today]


# ---------- Notifiche (ntfy) ----------

def fmt_eur(v):
    """869.79 -> '869,79 €'"""
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_day(d):
    return f"{d[8:10]}/{d[5:7]}"


def local_settings():
    """Legge tracker.conf: righe chiave=valore, # per i commenti."""
    conf = {}
    if CONF.exists():
        for line in CONF.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                conf[key.strip().lower()] = value.split("#")[0].strip()
    return conf


def ntfy_settings():
    """Topic e server ntfy da tracker.conf o dalle variabili NTFY_TOPIC / NTFY_SERVER.

    Restituisce None se il topic non è configurato: in quel caso niente notifiche.
    """
    local = local_settings()
    conf = {"server": local.get("ntfy_server") or "https://ntfy.sh",
            "topic": local.get("ntfy_topic"),
            "dashboard": local.get("dashboard") or DASHBOARD}
    for key in ("topic", "server"):
        if os.environ.get("NTFY_" + key.upper()):
            conf[key] = os.environ["NTFY_" + key.upper()]
    return conf if conf.get("topic") else None


def build_alert(product, before, clean):
    """Messaggio di avviso per un prodotto, oppure None se non c'è niente di nuovo.

    Avvisa quando il prezzo minimo di oggi:
    - è sotto (o pari) all'obiettivo, ed è la prima volta o è sceso ancora rispetto all'ultima rilevazione;
    - è un nuovo minimo storico (strettamente più basso di tutti i giorni precedenti).
    """
    price, best = clean[0]["price"], clean[0]
    target = product.get("target")
    last = before[-1] if before else None
    reasons, priority = [], 3

    if target and price <= target and (last is None or last["min_price"] > target or price < last["min_price"]):
        gap = target - price
        reasons.append(f"Sotto l'obiettivo di {fmt_eur(target)}" + (f" di {fmt_eur(gap)}" if gap else ""))
        priority = 4
    if before:
        low = min(before, key=lambda h: h["min_price"])
        if price < low["min_price"]:
            reasons.append(f"Nuovo minimo storico (prima {fmt_eur(low['min_price'])} il {fmt_day(low['date'])})")
    if not reasons:
        return None

    return {
        "title": f"{product['name']}: {fmt_eur(price)}",
        "message": "\n".join(reasons + [f"{best['shop']} · {best['model']}"]),
        "priority": priority,
        "tags": ["moneybag"] if priority == 4 else ["chart_with_downwards_trend"],
        "click": best["url"],
        "price": price,
    }


def send_ntfy(conf, alert):
    """Pubblica una notifica in formato JSON (accetta titoli con € e accenti)."""
    body = {"topic": conf["topic"], "title": alert["title"], "message": alert["message"],
            "priority": alert.get("priority", 3), "tags": alert.get("tags", [])}
    if alert.get("click"):
        body["click"] = alert["click"]
    if conf.get("dashboard"):
        body["actions"] = [{"action": "view", "label": "Dashboard", "url": conf["dashboard"]}]
    req = urllib.request.Request(conf["server"].rstrip("/") + "/", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


def warn(title, message):
    """Notifica di servizio immediata (es. verifica da risolvere); silenziosa se ntfy non c'è."""
    conf = ntfy_settings()
    print(f"{title}: {message}", file=sys.stderr)
    if conf:
        try:
            send_ntfy(conf, {"title": title, "message": message, "priority": 4, "tags": ["warning"]})
        except Exception as e:
            print(f"Notifica non inviata: {e}", file=sys.stderr)


def notify(alerts, sent_today):
    """Manda gli avvisi non ancora mandati oggi allo stesso prezzo. Restituisce quelli inviati."""
    conf = ntfy_settings()
    sent = dict(sent_today)
    if not conf:
        if alerts:
            print(f"{len(alerts)} avvisi, ma ntfy non è configurato (vedi README).")
        return sent
    for pid, alert in alerts.items():
        if sent.get(pid) == alert["price"]:
            continue  # già avvisato oggi a questo prezzo (es. rilevazione rifatta con FORCE=1)
        try:
            send_ntfy(conf, alert)
            sent[pid] = alert["price"]
            print(f"Notifica inviata: {alert['title']}")
        except Exception as e:  # una notifica fallita non deve far fallire la rilevazione
            print(f"Notifica non inviata ({alert['title']}): {e}", file=sys.stderr)
    return sent


def collect(product, session, report, updated, alerts, now, today):
    """Legge un prodotto da tutti i negozi, salva i dati e prepara l'eventuale avviso."""
    shops = dict(SHOPS)
    if session:
        shops["Trovaprezzi"] = ("trovaprezzi", lambda q: session.trovaprezzi(q, product["id"]))
    offers, status = [], {}
    for shop, (key, fn) in shops.items():
        if not product.get(key):
            continue
        try:
            found = fn(product[key])
            status[shop] = f"ok ({len(found)})"
            offers += found
        except Exception as e:  # un negozio che fallisce non ferma gli altri
            status[shop] = f"errore: {e}"
        time.sleep(PAUSE)

    clean = clean_offers(product, offers)
    report[product["id"]] = {"sources": status, "offers": len(clean)}
    if clean:
        before = save_product(product, clean, status, now, today)
        updated.append(product["id"])
        alert = build_alert(product, before, clean)
        if alert:
            alerts[product["id"]] = alert
        print(f"{product['name']}: {len(clean)} offerte, minimo {clean[0]['price']} € "
              f"({clean[0]['shop']}) {status}")
    else:
        # niente offerte valide oggi: tengo i dati di ieri
        print(f"{product['name']}: nessuna offerta valida {status}", file=sys.stderr)


def main(only=None):
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Europe/Rome")).date().isoformat()  # giorno italiano
    report, updated, alerts = {}, [], {}
    session = browser_session()
    try:
        for product in PRODUCTS:
            if only and product["id"] not in only:
                continue
            collect(product, session, report, updated, alerts, now, today)
    finally:
        if session:
            session.close()

    (DATA / "products.json").write_text(json.dumps(
        {"groups": GROUPS,
         "products": [{k: p.get(k) for k in ("id", "group", "name", "target", "specs")} for p in PRODUCTS]},
        ensure_ascii=False, indent=1))

    if not updated:
        print("Nessun prodotto aggiornato: probabilmente i negozi bloccano la lettura.", file=sys.stderr)
        sys.exit(1)

    status_path = DATA / "status.json"
    old = json.loads(status_path.read_text()) if status_path.exists() else {}
    sent_today = old.get("notified", {}) if old.get("date") == today else {}
    sent = notify(alerts, sent_today)

    status_path.write_text(json.dumps(
        {"date": today, "updated": now.isoformat(timespec="seconds"), "products": report,
         "notified": sent},
        ensure_ascii=False, indent=1))
    print(f"{today}: aggiornati {len(updated)} prodotti su {len(report)}")


def test_notify():
    conf = ntfy_settings()
    if not conf:
        sys.exit(f"ntfy non configurato: manca ntfy_topic in {CONF.name} o la variabile NTFY_TOPIC.")
    send_ntfy(conf, {"title": "Tracker prezzi: prova", "priority": 3, "tags": ["white_check_mark"],
                     "message": "Se leggi questo messaggio, le notifiche funzionano."})
    print(f"Notifica di prova inviata a {conf['server']} (topic configurato).")


if __name__ == "__main__":
    # python tracker.py                 -> tutti i prodotti
    # python tracker.py rx9070xt        -> solo quelli indicati
    # python tracker.py --test-notify   -> manda solo una notifica di prova
    if "--test-notify" in sys.argv:
        test_notify()
    else:
        main(set(sys.argv[1:]) or None)
