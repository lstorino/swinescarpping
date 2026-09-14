"""Pig333 markets_and_prices scraper — resilient, AI-free, 2 HTTP GETs per run.

Three-tier extraction (scrapling philosophy — docs/tutorials/replacing_ai):
  Tier 1: CSS selectors via Scrapling Selector (fast path, current layout)
  Tier 2: Content-based selection: find_by_text / find_by_regex
          (survives class renames — the 2020->2026 layout change case)
  Tier 3: Regex over the raw HTML (last resort, still deterministic)

Fetching is stdlib urllib — scrapling's Fetcher pulls playwright/curl_cffi
(heavy deps for a 2-GET job). Scrapling is used for what it's worth here:
its resilient parsing layer (Selector + content-based matching).
"""
from __future__ import annotations

import json
import re
import urllib.request

from scrapling import Selector

PIG333_URL = "https://www.pig333.com/markets_and_prices/"
FX_URL = "https://open.er-api.com/v6/latest/USD"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# ---------------------------------------------------------------------------
# Unit normalization (fixes the 2020 bug: cwt and pence were ignored)
# ---------------------------------------------------------------------------

LB_PER_KG = 0.45359237          # 1 lb in kg
CWT_KG = 100 * LB_PER_KG        # 1 cwt = 45.359237 kg
GBX_PER_GBP = 100               # pence -> GBP

# Multipliers turning "price per <unit>" into "price per kg".
#   None  -> unit cannot be weight-converted (per-head piglet prices)
UNIT_TO_KG = {
    "kg": 1.0,
    "100kg": 1 / 100,           # price per 100kg -> per kg
    "cwt": 1 / CWT_KG,          # price per hundredweight -> per kg
    "un": None,                 # per head (piglets) — not a weight price
}

# Currencies that are sub-units of a currency present in the FX feed.
SUB_UNIT_PARENT = {"GBX": ("GBP", GBX_PER_GBP)}

# pig333 renders high-magnitude currencies with dot-as-thousands-separator
# ('7.090' KRW = 7090). Low-magnitude currencies use the dot as a decimal
# point ('1.960' EUR = 1.96, '4.850' BRL = 4.85), so the strip rule is
# currency-gated and only fires on the exact grouped shape.
THOUSANDS_DOT = {
    "KRW", "VND", "CLP", "COP", "ARS", "HUF", "IDR", "PHP", "MYR",
    "THB", "JPY", "TWD", "RUB", "UAH",
}
GROUPED_RE = re.compile(r"\d{1,3}(?:\.\d{3})+")


def parse_price(text: str, currency: str) -> float:
    """Parse a pig333 price string into a float, currency-aware."""
    t = text.strip()
    if currency.upper() in THOUSANDS_DOT and GROUPED_RE.fullmatch(t):
        return float(t.replace(".", ""))
    return float(t.replace(",", "."))


def usd_per_kg(price: float, currency: str, unit: str) -> float | None:
    """Normalize to USD per kg. None if not weight-based or rate missing.

    The FX feed is USD-based (rates[X] = X per 1 USD), so:
        usd_price = local_price / rate[currency]
    """
    unit_factor = UNIT_TO_KG.get(unit.lower())
    if unit_factor is None:
        return None  # per-head price — keep raw, flag as not comparable

    cur = currency.upper()
    sub = SUB_UNIT_PARENT.get(cur)
    if sub:
        parent, factor = sub
        price = price / factor
        cur = parent

    rate = FX_RATES.get(cur)
    if rate is None:
        return None
    return price / rate * unit_factor


# ---------------------------------------------------------------------------
# Fetch (1 GET for the page, 1 GET for FX — the whole run)
# ---------------------------------------------------------------------------

FX_RATES: dict[str, float] = {}


def fetch_fx() -> dict[str, float]:
    global FX_RATES
    req = urllib.request.Request(FX_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("result") == "error":
        raise RuntimeError(f"FX API error: {data.get('error-type')}")
    FX_RATES = data["rates"]
    return FX_RATES


def fetch_page() -> tuple[Selector, str]:
    """Return (parsed page, raw html) — tier 3 needs the raw string."""
    req = urllib.request.Request(PIG333_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    return Selector(html), html


# ---------------------------------------------------------------------------
# Regexes — tier 3 (raw HTML slicing; also used for per-block extraction,
# which is more precise than DOM walks on this page)
# ---------------------------------------------------------------------------

BLOCK_RE = re.compile(
    r"<div class='preu_mercat' data-id='(\d+)'>(.*?)<div class='clear'></div></div>",
    re.S,
)
FLAG_RE = re.compile(r"flags/([a-z]{2})\.svg")
TITLE_RE = re.compile(r"class='titol[^>]*>([^<]+)</a>")
REF_RE = re.compile(r"<span class='data fs9'>(.*?)</span>", re.S)
DATE_RE = re.compile(r"<span class='data'>([^<]+)</span>")
PRICE_RE = re.compile(r"<span class='preu'>([^<]+)</span>")
CUR_RE = re.compile(r"<span class='moneda'>([^<]+)</span>")
UNIT_RE = re.compile(r"<span class='unitats'>([^<]+)</span>")
PERC_RE = re.compile(r"perc[^>]*>([^<]*)</span>")
NUM_RE = re.compile(r"<span class='num ([^']*)'>([^<]*)</span>")
REGION_RE = re.compile(
    r"<h3 class='card-title'>([^<]+)</h3>(.*?)(?=<h3 class='card-title'>|$)", re.S
)
CAT_RE = re.compile(
    r"<div class='tipus_categoria'>([^<]*)</div>(.*?)(?=<div class='tipus_categoria'>|$)",
    re.S,
)


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def parse_blocks(html: str, region: str, category: str) -> list[dict]:
    """Extract every market block from one (region, category) slice of HTML."""
    markets = []
    for m in BLOCK_RE.finditer(html):
        block = m.group(2)

        def one(pattern, default=None):
            mm = pattern.search(block)
            return mm.group(1).strip() if mm else default

        price_raw = one(PRICE_RE)
        if price_raw is None:
            continue  # market without a published price this week

        num_m = NUM_RE.search(block)
        delta_class = num_m.group(1).strip() if num_m else ""
        delta_raw = num_m.group(2).strip() if num_m else ""
        # 'down'/'up' direction comes from the num span's class; the trailing
        # pct (pig333's own math — occasionally glitchy, e.g. KRW 2026-09-10)
        # is stored raw so glitches are detectable downstream.
        currency = one(CUR_RE, "")

        markets.append(
            {
                "market_id": int(m.group(1)),
                "region": region,
                "category": category,
                "flag": one(FLAG_RE, ""),
                "country": one(TITLE_RE, "?"),
                "reference": _strip_tags(one(REF_RE, "")),
                "date": one(DATE_RE, ""),
                "price": parse_price(price_raw, currency),
                "currency": currency,
                "unit": one(UNIT_RE, ""),
                "variation": _strip_tags(one(PERC_RE, "0%")),
                "delta": delta_raw,
                "delta_class": delta_class,
            }
        )
    return markets


def _region_slice_tier2(page: Selector, region: str) -> str | None:
    """Tier 2: content-anchored location of a region card via Scrapling."""
    try:
        heads = page.find_by_text(region, first_match=True)
    except Exception:
        return None
    if not heads:
        return None
    h = heads
    node = h
    for _ in range(6):
        node = node.parent
        if node is None:
            return None
        if "card-sm" in (node.attrib.get("class") or ""):
            return node.html
    return None


def parse_all(page: Selector, raw_html: str) -> list[dict]:
    """Full parse: every region, every category — three tiers."""
    rows: list[dict] = []

    # Region slices are derived dynamically — the page grew an "Africa" card
    # between 2020 and 2026, so never hardcode the region list.
    slices: dict[str, str] = {}
    for m in REGION_RE.finditer(raw_html):
        slices[m.group(1).strip()] = m.group(2)

    for region, seg in slices.items():
        if seg is None:
            continue

        for cm in CAT_RE.finditer(seg):
            category = cm.group(1).strip()
            rows.extend(parse_blocks(cm.group(2), region, category))

    # Last resort if nothing matched at all: whole-document tier 3
    if not rows:
        for m in REGION_RE.finditer(raw_html):
            for cm in CAT_RE.finditer(m.group(2)):
                rows.extend(
                    parse_blocks(cm.group(2), m.group(1).strip(), cm.group(1).strip())
                )
    return rows


def scrape_all() -> list[dict]:
    """One full run: 2 GETs (page + FX). Returns normalized rows."""
    fetch_fx()
    page, raw_html = fetch_page()
    rows = parse_all(page, raw_html)
    for r in rows:
        r["usd_per_kg"] = usd_per_kg(r["price"], r["currency"], r["unit"])
    return rows


if __name__ == "__main__":
    import sys

    rows = scrape_all()
    out = sys.argv[1] if len(sys.argv) > 1 else "data/prices_snapshot.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"{len(rows)} markets -> {out}")