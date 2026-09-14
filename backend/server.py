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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# repo layout: backend/server.py -> ../scraper; docker layout: /app/server.py
# -> ./scraper. Probe both so the same file runs unmodified in each.
for _cand in (os.path.join(ROOT, "scraper"), os.path.join(HERE, "scraper")):
    if os.path.exists(os.path.join(_cand, "pig333.py")):
        sys.path.insert(0, _cand)
        break
import pig333  # noqa: E402
import status_page  # noqa: E402  (sits next to server.py in both layouts)

DB_PATH = os.environ.get("PIG_DB", os.path.join(os.path.dirname(__file__), "data", "pigprices.db"))
TOKEN = os.environ.get("PIG_TOKEN", "")
PORT = int(os.environ.get("PIG_PORT", "8902"))
FLAG_DIR = os.path.join(HERE, "flags")
LAST_PUSH: list[str | None] = [None]


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


def ingest_rows(rows: list[dict]) -> dict:
    """Upsert a snapshot pushed by a home-side collector (NAS)."""
    required = {"market_id", "region", "category", "flag", "country", "date",
                "price", "currency", "unit", "usd_per_kg", "reference"}
    now = utcnow()
    conn = db()
    try:
        with conn:
            for r in rows:
                missing = required - set(r)
                if missing:
                    raise ValueError(f"row missing fields: {missing}")
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
                     r["usd_per_kg"], r["reference"], r.get("variation", ""),
                     r.get("delta", ""), r.get("delta_class", "")),
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
        last = conn.execute("SELECT MAX(scraped_at) FROM history").fetchone()[0]
        if last:
            LAST_PUSH[0] = last
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

    def _html(self, code: int, body: str, headers: list[tuple[str, str]] | None = None):
        payload = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for h in headers or []:
            self.send_header(*h)
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, loc: str, headers: list[tuple[str, str]] | None = None):
        self.send_response(302)
        self.send_header("Location", loc)
        for h in headers or []:
            self.send_header(*h)
        self.end_headers()

    def _session_ok(self) -> bool:
        return status_page.check_session(self.headers.get("Cookie"))

    def _flags(self):
        m = re.match(r"^/flags/([a-z]{2})\.svg$", self.path)
        if not m:
            self._send(404, {"error": "no such flag"})
            return
        path = os.path.join(FLAG_DIR, f"{m.group(1)}.svg")
        if not os.path.exists(path):
            self._send(404, {"error": "no such flag"})
            return
        payload = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Cache-Control", "public, max-age=604800")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            if self._session_ok():
                payload = latest_payload()
                self._html(200, status_page.dashboard_page(
                    payload["markets"], payload["total_history_rows"],
                    payload["generated_at"], LAST_PUSH[0] or "never"))
            else:
                self._html(200, status_page.login_page())
        elif path == "/logout":
            self._redirect("/", [("Set-Cookie", "pigsess=; Max-Age=0; Path=/")])
        elif path.startswith("/flags/"):
            self._flags()
        else:
            self._api_get()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/login":
            length = int(self.headers.get("Content-Length", "0"))
            form = self.rfile.read(length).decode("utf-8", "replace")
            key = ""
            for pair in form.split("&"):
                k, _, v = pair.partition("=")
                if k == "key":
                    key = v
            if status_page.check_key(key):
                self._redirect("/", [("Set-Cookie",
                                      f"pigsess={status_page.make_session()}; "
                                      "Max-Age=604800; Path=/; HttpOnly")])
            else:
                self._html(200, status_page.login_page("wrong key"))
        else:
            self._api_post()

    # --- API routes (token-protected) ---
    def _api_get(self):
        m = re.search(r"[?&]token=([^&]+)", self.path)
        tok = m.group(1) if m else (self.headers.get("X-Pig-Token") or "")
        if TOKEN and tok != TOKEN:
            self._send(401, {"error": "bad token"})
            return

        if self.path.startswith("/prices.json") or self.path.startswith("/prices"):
            self._send(200, latest_payload())
        elif self.path.startswith("/health"):
            self._send(200, {"ok": True, "time": utcnow(), "last_push": LAST_PUSH[0]})
        else:
            self._send(404, {"error": "not found"})

    def _api_post(self):
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
        elif self.path.startswith("/ingest"):
            # Home-side collector (NAS) pushes a snapshot it scraped locally —
            # pig333 blocks datacenter IPs, so collection happens on the home
            # network and history still lands in this DB.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                rows = payload.get("rows", [])
                if not rows:
                    self._send(400, {"ok": False, "error": "no rows"})
                    return
                summary = ingest_rows(rows)
                LAST_PUSH[0] = utcnow()
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