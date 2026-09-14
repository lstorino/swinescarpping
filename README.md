# swinescarpping → Pig333 World Pig Price Tracker

Scrapes pig333.com's markets_and_prices page for live pig/pork prices per
country, normalizes everything to **USD per kg**, and feeds a macOS desktop
widget + a history backend on the VPS (curves over time per market).

## Layout

- `scraper/pig333.py` — the parser (stdlib fetch + Scrapling parsing tiers)
- `backend/` — VPS service: SQLite history, JSON endpoint for the widget
- `macos-widget/` — macOS NSPanel desktop widget (flags, USD/kg, observation)
- `archive/` — the original 2020 notebooks and CSVs
- `data/prices_snapshot.json` — latest local snapshot (regenerated per run)

## What the scraper captures per market

| field | example | source |
|---|---|---|
| market_id | 90 | pig333 data-id |
| region / category | Asia / FATTENING PIGS | region card + section header |
| flag | kr | flags/kr.svg |
| country | South Korea | card title |
| reference | "Ekapepia Carcass" | observation label (source + basis) |
| date | 10 Sep | last published price date |
| price / currency / unit | 7090 KRW kg | published values |
| variation | 99.9% | pig333's own week-over-week % |
| delta / delta_class | 7079 / down | absolute change + direction |
| **usd_per_kg** | 5.281 | computed locally |

## Normalization rules (the fixes vs 2020)

The old script ignored unit and sub-unit semantics (USA showed $0.76/kg
instead of $1.97 — cwt was never converted; UK pence likewise). Now:

- **kg** → as-is; **100kg** → ÷100; **cwt** → ÷ 45.359237 (100 lb)
- **un** (per head, piglets) → *not* convertible to a weight price; kept raw
- **GBX** (pence) → GBP ÷ 100 before FX
- **FX feed**: open.er-api.com (free, no key, daily) — USD-based rates
- **Thousands separator**: pig333 renders high-magnitude currencies with
  dot-as-thousands ('7.090' KRW = 7090). Currency-gated rule: strip dots only
  for KRW/VND/CLP/COP/ARS/HUF/IDR/PHP/MYR/THB/JPY/TWD/RUB/UAH and only on the
  exact grouped shape (so '1.960' EUR stays 1.96, '11.55' CNY stays 11.55).

## Parser resilience (scrapling philosophy — no AI, no cost)

Three tiers, per run exactly **2 HTTP GETs** (pig333 page + FX):

1. CSS selectors via Scrapling `Selector` (fast path)
2. Content-based selection (`find_by_text` / `find_by_regex`) when classes
   change (the 2020→2026 layout change case)
3. Raw-HTML regex slicing (regions/categories are discovered dynamically —
   the page grew an "Africa" card in 2026; nothing is hardcoded)

pig333's own glitched values are stored as published (e.g. Korea 2026-09-10
shows 99.9% because pig333 divides delta by the current price) — the raw
delta is captured so glitches stay detectable.

## Run

```bash
python scraper/pig333.py data/prices_snapshot.json
```

## Widget

macOS NSPanel (always-on-top option), three columns per row: **flag + country**
| **USD/kg** (tabular digits) | **observation** (source + basis, e.g.
"Danis · Live", "AHDB · slaughterhouse price"). Data from the VPS backend,
refreshed 2×/day. See `macos-widget/`.

## Considerations (deferred)

- Sparkline per row in the widget (needs accumulated history first)
- GitHub Actions CI + GHCR image build for the backend
- White-label multi-tenant packaging (Nexus-style reselling)
- pig333 per-market history pages as a backfill source for the DB