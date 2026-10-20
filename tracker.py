#!/usr/bin/env python3
"""Rileva i prezzi della Radeon RX 9070 XT nuova su alcuni negozi italiani.

Aggiorna docs/data/offers.json (offerte di oggi) e docs/data/history.json
(una riga per giorno). Solo libreria standard: nessuna dipendenza.
"""
import html
import json
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "docs" / "data"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"

# Il titolo deve parlare di una 9070 XT; scarta accessori e usato.
MODEL_RE = re.compile(r"9070\s*-?\s*XT", re.I)
EXCLUDE_RE = re.compile(
    r"waterblock|water block|backplate|cavo|supporto|staffa|bracket|riser|"
    r"ricondizionat|usat[oa]|refurbished|pc gaming|pc desktop|computer|notebook",
    re.I,
)
TOP_N = 10


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


def amazon():
    s = fetch("https://www.amazon.it/s?k=radeon+rx+9070+xt&i=computers")
    if "captcha" in s.lower() and "s-search-result" not in s:
        raise RuntimeError("captcha")
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


def mediaworld():
    s = fetch("https://www.mediaworld.it/it/search.html?query=rx%209070%20xt")
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
                out.append({"model": item["name"].split(",")[0].strip(), "shop": "MediaWorld",
                            "price": float(offer["price"]), "url": item.get("url", "")})
    return out


SOURCES = {"Amazon.it": amazon, "MediaWorld": mediaworld}


def main():
    offers, status = [], {}
    for name, fn in SOURCES.items():
        try:
            found = fn()
            status[name] = f"ok ({len(found)})"
            offers += found
        except Exception as e:  # un negozio che fallisce non ferma gli altri
            status[name] = f"errore: {e}"
        time.sleep(2)
    print(status)

    seen, clean = set(), []
    for o in offers:
        if not o["price"] or not MODEL_RE.search(o["model"]) or EXCLUDE_RE.search(o["model"]):
            continue
        # sotto i 400 € non è una 9070 XT nuova: è un accessorio o un errore
        if o["price"] < 400 or o["url"] in seen:
            continue
        seen.add(o["url"])
        clean.append(o)
    clean.sort(key=lambda o: o["price"])

    if not clean:
        print("Nessuna offerta trovata: non aggiorno i dati.", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    rows = [{"rank": i + 1, **o} for i, o in enumerate(clean)]
    (DATA / "offers.json").write_text(json.dumps(
        {"updated": now.isoformat(timespec="seconds"), "sources": status, "offers": rows},
        ensure_ascii=False, indent=1))

    hist_path = DATA / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else []
    history = [h for h in history if h["date"] != today]
    by_shop = {}
    for o in clean:
        by_shop.setdefault(o["shop"], o["price"])
    history.append({
        "date": today,
        "min_price": clean[0]["price"],
        "avg_top10": round(statistics.mean(o["price"] for o in clean[:TOP_N]), 2),
        "offers": len(clean),
        "cheapest_model": clean[0]["model"],
        "cheapest_shop": clean[0]["shop"],
        "by_shop": by_shop,
        "source": "negozi",
    })
    history.sort(key=lambda h: h["date"])
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=1))
    print(f"{today}: {len(clean)} offerte, minimo {clean[0]['price']} € ({clean[0]['shop']})")


if __name__ == "__main__":
    main()
