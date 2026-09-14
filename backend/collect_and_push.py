"""Home-side collector: scrape pig333 locally, push to the VPS backend.

Runs on the NAS (or any always-on home machine) — pig333 403s datacenter
IPs, so collection must come from a residential IP. Stdlib only.

  python3 collect_and_push.py            # scrape + push
  python3 collect_and_push.py --dry-run  # scrape only, print summary
"""
from __future__ import annotations  # NAS python is 3.8: keep annotations lazy

import json
import os
import ssl
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _cand in (os.path.join(ROOT, "scraper"), os.path.join(HERE, "scraper")):
    if os.path.exists(os.path.join(_cand, "pig333.py")):
        sys.path.insert(0, _cand)
        break
import pig333  # noqa: E402

BACKEND = os.environ.get("PIG_BACKEND", "https://pigs.maytek.co")
TOKEN = os.environ.get("PIG_TOKEN", "")


def push(rows: list[dict]) -> dict:
    payload = json.dumps({"rows": rows}).encode()
    req = urllib.request.Request(
        f"{BACKEND}/ingest?token={TOKEN}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # NAS python may lack fresh CAs; verify by default, fall back once.
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except ssl.SSLError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.load(r)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    rows = pig333.scrape_all()
    print(f"scraped {len(rows)} markets")
    if dry:
        for r in rows[:5]:
            print(" ", r["flag"], r["country"], r["price"], r["currency"],
                  "->", r["usd_per_kg"])
        raise SystemExit(0)
    if not TOKEN:
        raise SystemExit("PIG_TOKEN env var required")
    result = push(rows)
    print("push:", result)