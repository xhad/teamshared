"""Zero-dependency HTML for the ``/admin`` dashboard (K1).

Server-rendered f-string HTML in the same style as ``dashboard.py`` (no JS/CSS
deps). Read-only pages over :class:`AdminService` + ``ProductionServices``,
gated by a magic-link session cookie. Everything is escaped at the boundary.
"""

from __future__ import annotations

from html import escape
from typing import Any

_NAV = [
    ("/admin", "Overview"),
    ("/admin/members", "Members"),
    ("/admin/agents", "Agents"),
    ("/admin/roles", "Roles"),
    ("/admin/api-keys", "API keys"),
    ("/admin/approvals", "Approvals"),
    ("/admin/audit", "Audit"),
    ("/admin/retention", "Retention"),
    ("/admin/connectors", "Connectors"),
]

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  margin: 0; background: #f7f7fb; color: #1f2330; line-height: 1.5; }
header { background: #1f2330; color: #fff; padding: 1rem 1.5rem; display: flex;
  align-items: center; justify-content: space-between; }
header .who { font-size: .85rem; color: #c7cad6; }
nav { display: flex; flex-wrap: wrap; gap: .25rem; padding: .5rem 1.5rem; background: #2a2f40; }
nav a { color: #d7dae6; text-decoration: none; padding: .35rem .7rem; border-radius: 6px; font-size: .9rem; }
nav a:hover { background: #3a4055; }
main { max-width: 1100px; margin: 1.5rem auto; padding: 0 1.5rem; }
h1 { font-size: 1.4rem; margin: 0 0 1rem; }
.panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #eef0f6; vertical-align: top; }
th { color: #6b7280; text-transform: uppercase; font-size: .72rem; letter-spacing: .04em; }
.empty { color: #9ca3af; padding: .75rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap: 1rem; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 1rem 1.25rem; }
.card .num { font-size: 1.8rem; font-weight: 700; }
.card .label { font-size: .8rem; color: #6b7280; text-transform: uppercase; }
form.login { max-width: 380px; margin: 4rem auto; background: #fff; border: 1px solid #e5e7eb;
  border-radius: 12px; padding: 2rem; }
input[type=email] { width: 100%; padding: .6rem; border: 1px solid #d1d5db; border-radius: 8px; font-size: 1rem; }
button { margin-top: 1rem; padding: .6rem 1rem; background: #4f46e5; color: #fff; border: 0;
  border-radius: 8px; font-size: 1rem; cursor: pointer; }
.note { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 8px; padding: .75rem 1rem; margin: 1rem 0; font-size: .9rem; }
.err { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; }
a.code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
"""


def _nav(active: str) -> str:
    links = "".join(
        f'<a href="{escape(href)}"'
        + (' style="background:#4f46e5;color:#fff"' if href == active else "")
        + f">{escape(label)}</a>"
        for href, label in _NAV
    )
    return f"<nav>{links}</nav>"


def page(title: str, body: str, *, active: str = "/admin", who: str | None = None) -> str:
    who_html = f'<span class="who">{escape(who)} &middot; <a href="/admin/logout" style="color:#fca5a5">sign out</a></span>' if who else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} &middot; teamshared admin</title>
<style>{_CSS}</style></head>
<body>
<header><strong>teamshared admin</strong>{who_html}</header>
{_nav(active)}
<main><h1>{escape(title)}</h1>{body}</main>
</body></html>"""


def login_page(*, message: str | None = None, magic_link: str | None = None, error: bool = False) -> str:
    note = ""
    if message:
        cls = "note err" if error else "note"
        note = f'<div class="{cls}">{escape(message)}</div>'
    if magic_link:
        note += f'<div class="note">Dev sign-in link: <a class="code" href="{escape(magic_link)}">{escape(magic_link)}</a></div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in &middot; teamshared admin</title>
<style>{_CSS}</style></head>
<body>
<form class="login" method="post" action="/admin/login">
<h1>teamshared admin</h1>
{note}
<label for="email">Owner email</label>
<input id="email" name="email" type="email" placeholder="you@example.com" required autofocus>
<button type="submit">Send magic link</button>
</form>
</body></html>"""


def table(columns: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<div class="panel"><div class="empty">Nothing here yet.</div></div>'
    head = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = ""
    for row in rows:
        cells = "".join(f"<td>{escape(str(v)) if v is not None else '—'}</td>" for v in row)
        body += f"<tr>{cells}</tr>"
    return f'<div class="panel"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def cards(items: list[tuple[str, Any]]) -> str:
    cs = "".join(
        f'<div class="card"><div class="num">{escape(str(v))}</div>'
        f'<div class="label">{escape(label)}</div></div>'
        for label, v in items
    )
    return f'<div class="cards">{cs}</div>'


def error_page(code: int, message: str) -> str:
    body = f'<div class="panel"><div class="note err">{escape(message)}</div></div>'
    return page(f"{code}", body)
