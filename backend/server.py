"""Pig prices backend — SQLite history + JSON API for the macOS widget.

One process, three jobs:
  - scrape: pig333 page -> rows -> insert into history (idempotent per
    (market_id, date) so re-runs never duplicate; re-running the same day
    with a revised price overwrites that day's row)
  - serve: GET /prices.json?token=... -> widget payload
  - log: every run appended to history for curve analysis over time

Stdlib only (no flask/fastapi) — cheap on every run, tiny image.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scraper"))
import pig333  # noqa: E402

DB_PATH = os.environ.get("PIG_DB", os.path.join(os.path.dirname(__file__), "data", "pigprices.db"))
TOKEN = os.environ.get("PIG_TOKEN", "")
PORT = int(os.environ.get("PIG_PORT", "8902"))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    market_id     INTEGER PRIMARY KEY,
    country       TEXT,
    region        TEXT,
    category      TEXT,
    flag          TEXT
);
CREATE TABLE IF NOT EXISTS history (
    market_id     INTEGER NOT NULL,
    price_date    TEXT NOT NULL,      -- as published by pig333 ('10 Sep')
    scraped_at    TEXT NOT NULL,      -- ISO UTC of the scrape run
    price         REAL,
    currency      TEXT,
    unit          TEXT,
    usd_per_kg    REAL,
    reference     TEXT,
    variation     TEXT,
    delta         TEXT,
    delta_class   TEXT,
    PRIMARY KEY (market_id, price_date)
);
CREATE INDEX IF NOT EXISTS idx_hist_market ON history(market_id, scraped_at);
"""


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def run_scrape() -> dict:
    """Scrape pig333 + FX, upsert markets + history rows. Returns summary."""
    rows = pig333.scrape_all()
    now = utcnow()
    conn = db()
    try:
        with conn:
            for r in rows:
                conn.execute(
                    "INSERT INTO markets (market_id, country, region, category, flag) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(market_id) DO UPDATE SET "
                    "country=excluded.country, region=excluded.region, "
                    "category=excluded.category, flag=excluded.flag",
                    (r["market_id"], r["country"], r["region"], r["category"], r["flag"]),
                )
                conn.execute(
                    "INSERT INTO history (market_id, price_date, scraped_at, price, "
                    "currency, unit, usd_per_kg, reference, variation, delta, delta_class) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(market_id, price_date) DO UPDATE SET "
                    "scraped_at=excluded.scraped_at, price=excluded.price, "
                    "currency=excluded.currency, unit=excluded.unit, "
                    "usd_per_kg=excluded.usd_per_kg, reference=excluded.reference, "
                    "variation=excluded.variation, delta=excluded.delta, "
                    "delta_class=excluded.delta_class",
                    (r["market_id"], r["date"], now, r["price"], r["currency"], r["unit"],
                     r["usd_per_kg"], r["reference"], r["variation"], r["delta"], r["delta_class"]),
                )
    finally:
        conn.close()
    return {"scraped_at": now, "markets": len(rows)}


# ---------------------------------------------------------------------------
# API — token-protected, mirrors Nestor's widget endpoint shape
# ---------------------------------------------------------------------------

def latest_payload() -> dict:
    """Widget payload: latest row per market + spark data (30 points)."""
    conn = db()
    try:
        cur = conn.execute(
            """
            SELECT h.*, m.country, m.flag, m.region, m.category
            FROM history h
            JOIN (SELECT market_id, MAX(scraped_at) AS ms FROM history
                  GROUP BY market_id) t
            ON h.market_id = t.market_id AND h.scraped_at = t.ms
            JOIN markets m ON m.market_id = h.market_id
            ORDER BY m.region, m.category, h.market_id
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    finally:
        conn.close()
    return {
        "generated_at": utcnow(),
        "total_history_rows": total,
        "markets": rows,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        # token check: ?token= or X-Pig-Token header
        m = re.search(r"[?&]token=([^&]+)", self.path)
        tok = m.group(1) if m else (self.headers.get("X-Pig-Token") or "")
        if TOKEN and tok != TOKEN:
            self._send(401, {"error": "bad token"})
            return

        if self.path.startswith("/prices.json") or self.path.startswith("/prices"):
            self._send(200, latest_payload())
        elif self.path.startswith("/health"):
            self._send(200, {"ok": True, "time": utcnow()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        m = re.search(r"[?&]token=([^&]+)", self.path)
        tok = m.group(1) if m else (self.headers.get("X-Pig-Token") or "")
        if TOKEN and tok != TOKEN:
            self._send(401, {"error": "bad token"})
            return
        if self.path.startswith("/scrape"):
            try:
                summary = run_scrape()
                self._send(200, {"ok": True, **summary})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, format, *args):  # noqa: A002  # quiet
        print(f"{utcnow()} {self.address_string()} {format % args}")


def serve():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{utcnow()} pigprices API on :{PORT}", flush=True)
    server.serve_forever()


# ---------------------------------------------------------------------------
# CLI:  python server.py scrape   (cron job entrypoint)
#       python server.py serve    (API container entrypoint)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if mode == "scrape":
        print(json.dumps(run_scrape()))
    elif mode == "serve":
        if os.environ.get("PIG_SCRAPE_ON_START"):
            try:
                print(json.dumps(run_scrape()))
            except Exception as e:  # noqa: BLE001
                print(f"startup scrape failed: {e}", file=sys.stderr)
        serve()
    else:
        print("usage: server.py [scrape|serve]", file=sys.stderr)
        raise SystemExit(2)