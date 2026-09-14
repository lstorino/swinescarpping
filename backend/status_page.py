"""Pig prices status page — login + dashboard + collector health.

Used by server.py's handler subclass. Auth: session cookie signed with
HMAC over PIG_TOKEN (the same secret the API uses).
"""
from __future__ import annotations

import html
import hmac
import os
import secrets

COOKIE = "pigsess"


def make_session() -> str:
    sid = secrets.token_hex(16)
    return f"{sid}.{_sign(sid)}"


def _sign(sid: str) -> str:
    secret = os.environ.get("PIG_TOKEN", "").encode() or b"dev"
    return hmac.new(secret, sid.encode(), "sha256").hexdigest()


def check_session(cookie_header: str | None) -> bool:
    if not cookie_header:
        return False
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and "." in v:
            sid, _, sig = v.rpartition(".")
            return hmac.compare_digest(_sign(sid), sig)
    return False


def check_key(key: str) -> bool:
    want = os.environ.get("PIG_TOKEN", "")
    return bool(want) and hmac.compare_digest(key, want)


def _esc(s) -> str:
    return html.escape(str(s))


LOGIN_PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Pig Prices</title><style>
body{font-family:-apple-system,system-ui,sans-serif;background:#111;color:#eee;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#1c1c1e;padding:32px 40px;border-radius:14px;box-shadow:0 8px 30px #0009}
h1{font-size:18px;margin:0 0 18px;font-weight:600}
input{display:block;width:100%;box-sizing:border-box;margin:8px 0;padding:10px 12px;
border-radius:8px;border:1px solid #333;background:#2a2a2c;color:#eee;font-size:14px}
button{width:100%;padding:10px;margin-top:12px;border:0;border-radius:8px;
background:#e0502f;color:#fff;font-size:14px;font-weight:600;cursor:pointer}
.err{color:#ff6b60;font-size:12px;margin-top:8px}
</style></head><body><div class=card>
<h1>&#128055; Pig Prices — login</h1>
<form method=POST action=/login>
<input type=password name=key placeholder="Access key" autofocus>
<button>Sign in</button>
__ERR__
</form></div></body></html>"""


def login_page(err: str = "") -> str:
    err_html = f"<p class=err>{_esc(err)}</p>" if err else ""
    return LOGIN_PAGE.replace("__ERR__", err_html)


def dashboard_page(rows: list[dict], total_rows: int, generated_at: str,
                   last_push: str) -> str:
    sections: dict[str, list[dict]] = {}
    for r in rows:
        sections.setdefault(r["region"], []).append(r)

    parts = []
    for region in ("Europe", "America", "Asia", "Africa"):
        rs = sections.get(region, [])
        if not rs:
            continue
        trs = []
        for r in sorted(rs, key=lambda x: -(x["usd_per_kg"] or 0)):
            usd = f"{r['usd_per_kg']:.3f}" if r["usd_per_kg"] is not None else "—"
            var = (r.get("variation") or "").strip()
            cls = "down" if "down" in (r.get("delta_class") or "") else (
                "up" if "up" in (r.get("delta_class") or "") else "flat")
            trs.append(
                f"<tr><td><img src=/flags/{_esc(r['flag'])}.svg class=flag "
                f"alt={_esc(r['flag'])}></td>"
                f"<td>{_esc(r['country'])}</td><td class=num>{usd}</td>"
                f"<td class=obs>{_esc(r['reference'])} · {_esc(r['unit'])}</td>"
                f"<td class='{cls}'>{_esc(var)}</td>"
                f"<td class=dim>{_esc(r['price_date'])}</td></tr>")
        parts.append(f"<h2>{_esc(region)} ({len(rs)})</h2>"
                     f"<table><tbody>{''.join(trs)}</tbody></table>")

    page = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Pig Prices</title><style>
body{font-family:-apple-system,system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:20px}
h1{font-size:20px}h2{font-size:15px;color:#aaa;margin:24px 0 8px;text-transform:uppercase;letter-spacing:.05em}
table{border-collapse:collapse;width:100%;max-width:900px}
td{padding:6px 10px;border-bottom:1px solid #222;font-size:14px}
td.num{font-family:ui-monospace,Menlo,monospace;text-align:right;min-width:70px}
td.obs{color:#9a9aa0;font-size:12px}td.dim{color:#666;font-size:12px}
.up{color:#5fd67a}.down{color:#ff6b60}.flat{color:#666}
img.flag{width:20px;height:14px;border-radius:2px;vertical-align:middle}
.meta{color:#777;font-size:12px;margin:4px 0 0}
a{color:#7ab0ff}
</style></head><body>
<h1>&#128055; Pig Prices — USD/kg</h1>
<p class=meta>generated __GEN__ · history rows: __TOTAL__ ·
last collector push: __PUSH__ · <a href=/logout>logout</a></p>
__BODY__
</body></html>"""
    return (page
            .replace("__GEN__", _esc(generated_at))
            .replace("__TOTAL__", _esc(total_rows))
            .replace("__PUSH__", _esc(last_push or "never"))
            .replace("__BODY__", "\n".join(parts)))