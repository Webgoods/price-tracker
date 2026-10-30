#!/usr/bin/env python3
"""Rileva i prezzi dei prodotti in PRODUCTS su alcuni negozi italiani.

Per ogni prodotto aggiorna docs/data/<id>/offers.json (offerte di oggi) e
docs/data/<id>/history.json (una riga per giorno). Scrive anche
docs/data/products.json (elenco per la dashboard) e docs/data/status.json
(data dell'ultima rilevazione riuscita, usata da run-local.sh).
Solo libreria standard: nessuna dipendenza.
"""
import html
import json
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).parent / "docs" / "data"
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
        "match": [r"9070\s*-?\s*XT"],
        "exclude": USED + r"|waterblock|water block|backplate|cavo|supporto|staffa|bracket|riser|"
                          r"pc gaming|pc desktop|computer|notebook",
        "min_price": 400,
    },
    {
        "id": "gmktec-k8-plus", "group": "minipc", "name": "GMKtec K8 Plus", "target": 600,
        "specs": "Ryzen 7 8845HS · 2× SO-DIMM DDR5 · 2× M.2 · 2× LAN 2.5G · OCuLink · Win 11 Pro",
        "amazon": "gmktec k8 plus 8845hs 32gb", "mediaworld": "gmktec k8 plus",
        "match": [r"gmktec", r"K8\s*Plus", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "beelink-ser8", "group": "minipc", "name": "Beelink SER8", "target": 600,
        "specs": "Ryzen 7 8845HS/8745HS · 2× SO-DIMM DDR5 · 2× M.2 · 1× LAN 2.5G · molto silenzioso · Win 11 Pro",
        "amazon": "beelink ser8 32gb", "mediaworld": "beelink ser8",
        "match": [r"beelink", r"SER\s*8(?!\d)", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "geekom-a8-max", "group": "minipc", "name": "GEEKOM A8 Max", "target": 650,
        "specs": "Ryzen 7 8845HS/8745HS · 2× SO-DIMM DDR5 · 1× M.2 · 2× LAN 2.5G · garanzia 3 anni · Win 11 Pro",
        "amazon": "geekom a8 max", "mediaworld": "geekom a8 max",
        "match": [r"geekom", r"A8\s*Max", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "gmktec-m7-ultra", "group": "minipc", "name": "GMKtec M7 Ultra", "target": 520,
        "specs": "Ryzen 7 PRO 6850U · DDR5 dual channel · 2× M.2 · 2× LAN 2.5G Intel · OCuLink · Win 11 Pro",
        "amazon": "gmktec m7 ultra 32gb", "mediaworld": "gmktec m7",
        "match": [r"gmktec", r"\bM7\b", r"32\s*G"],
        "exclude": MINIPC_EXCLUDE, "min_price": 250,
    },
    {
        "id": "nipogi-am06-pro", "group": "minipc", "name": "NiPoGi AM06 Pro", "target": 450,
        "specs": "Ryzen 7 7730U · 32 GB DDR4 espandibile · M.2 + slot 2,5\" · 2× LAN 1G · Win 11 Pro",
        "amazon": "nipogi am06 pro 32gb", "mediaworld": "nipogi am06 pro",
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
    folder = DATA / product["id"]
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{"rank": i + 1, **o} for i, o in enumerate(clean)]
    (folder / "offers.json").write_text(json.dumps(
        {"updated": now.isoformat(timespec="seconds"), "sources": status, "offers": rows},
        ensure_ascii=False, indent=1))

    hist_path = folder / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else []
    history = [h for h in history if h["date"] != today]
    history.append(history_row(today, clean))
    history.sort(key=lambda h: h["date"])
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=1))


def main(only=None):
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Europe/Rome")).date().isoformat()  # giorno italiano
    report, updated = {}, []

    for product in PRODUCTS:
        if only and product["id"] not in only:
            continue
        offers, status = [], {}
        for shop, (key, fn) in SHOPS.items():
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
            save_product(product, clean, status, now, today)
            updated.append(product["id"])
            print(f"{product['name']}: {len(clean)} offerte, minimo {clean[0]['price']} € "
                  f"({clean[0]['shop']}) {status}")
        else:
            # niente offerte valide oggi: tengo i dati di ieri
            print(f"{product['name']}: nessuna offerta valida {status}", file=sys.stderr)

    (DATA / "products.json").write_text(json.dumps(
        {"groups": GROUPS,
         "products": [{k: p.get(k) for k in ("id", "group", "name", "target", "specs")} for p in PRODUCTS]},
        ensure_ascii=False, indent=1))

    if not updated:
        print("Nessun prodotto aggiornato: probabilmente i negozi bloccano la lettura.", file=sys.stderr)
        sys.exit(1)

    (DATA / "status.json").write_text(json.dumps(
        {"date": today, "updated": now.isoformat(timespec="seconds"), "products": report},
        ensure_ascii=False, indent=1))
    print(f"{today}: aggiornati {len(updated)} prodotti su {len(report)}")


if __name__ == "__main__":
    # python tracker.py              -> tutti i prodotti
    # python tracker.py rx9070xt     -> solo quelli indicati
    main(set(sys.argv[1:]) or None)
