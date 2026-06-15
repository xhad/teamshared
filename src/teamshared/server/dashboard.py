"""Public memory status dashboard served at ``GET /memory``.

A single server-rendered HTML page (zero JS/CSS dependencies) showing component
health, per-pillar stats with CSS/inline-SVG charts, and the most recent saved
records across all four pillars. Mirrors the f-string rendering convention used
by the install page. Every section degrades to "unavailable"
rather than 500 when a backing store is down.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from html import escape
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse

from teamshared.memory.types import MemoryRecord
from teamshared.server.health import check_components
from teamshared.server.state import ServerState

# Chart/segment palette — teal-forward, distinct from generic indigo AI palettes.
_PALETTE = ["#1a6b5c", "#0d9488", "#2d8a5e", "#b45309", "#9d4b6a", "#3d6b8c"]
_DASH = "\u2014"

_DASHBOARD_CSS = """
:root {
  color-scheme: light;
  --font-sans: "Instrument Sans", "Segoe UI", sans-serif;
  --font-serif: "Source Serif 4", Georgia, serif;
  --bg: oklch(0.985 0.006 95);
  --panel: oklch(1 0 0);
  --panel-2: oklch(0.975 0.007 94);
  --border: oklch(0.9 0.012 90);
  --text: oklch(0.28 0.02 70);
  --muted: oklch(0.48 0.02 75);
  --faint: oklch(0.62 0.015 78);
  --accent: oklch(0.42 0.09 175);
  --success: oklch(0.48 0.12 155);
  --danger: oklch(0.52 0.19 25);
  --warn: oklch(0.62 0.14 75);
  --warn-soft: oklch(0.96 0.04 85);
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: oklch(0.16 0.015 75);
    --panel: oklch(0.22 0.015 75);
    --panel-2: oklch(0.25 0.015 75);
    --border: oklch(0.32 0.015 75);
    --text: oklch(0.93 0.01 90);
    --muted: oklch(0.72 0.015 85);
    --faint: oklch(0.58 0.015 80);
    --accent: oklch(0.68 0.1 175);
    --warn-soft: oklch(0.3 0.04 85);
  }
}
* { box-sizing: border-box; }
body {
  font-family: var(--font-sans);
  margin: 0; padding: clamp(1.25rem, 1rem + 1.5vw, 2rem);
  background: var(--bg); color: var(--text); line-height: 1.55;
}
h1 { font-family: var(--font-serif); margin: 0 0 .25rem; font-size: clamp(1.45rem, 1.2rem + 1vw, 1.75rem); font-weight: 600; }
h2 { font-family: var(--font-serif); margin: 2rem 0 .75rem; font-size: 1.1rem; font-weight: 600; }
.muted { color: var(--faint); }
a { color: var(--accent); }
.bar-wrap { max-width: 68rem; margin: 0 auto; }
.badges { display: flex; flex-wrap: wrap; gap: .5rem; margin: .75rem 0 0; }
.badge {
  display: inline-flex; align-items: center; gap: .4rem;
  padding: .25rem .6rem; border-radius: 999px; font-size: .78rem;
  background: var(--panel-2); border: 1px solid var(--border);
}
.dot { width: .55rem; height: .55rem; border-radius: 50%; background: var(--faint); }
.dot.ok { background: var(--success); }
.dot.bad { background: var(--danger); }
.dot.warn { background: var(--warn); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .75rem; }
.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: .875rem; padding: 1rem 1.15rem;
}
.card .num { font-family: var(--font-serif); font-size: 1.85rem; font-weight: 600; }
.card .label { font-size: .72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
.card .sub { font-size: .76rem; color: var(--faint); margin-top: .25rem; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); gap: 1.25rem; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: .875rem; padding: 1.15rem 1.25rem; }
.panel h3 { margin: 0 0 1rem; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; color: var(--faint); font-weight: 600; }
.bar-row { display: grid; grid-template-columns: 7.5rem 1fr 2.5rem; align-items: center; gap: .65rem; margin: .45rem 0; }
.bar-row .name { font-size: .84rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-row .track { background: var(--panel-2); border-radius: .375rem; height: .5rem; overflow: hidden; }
.bar-row .fill { height: 100%; border-radius: .375rem; }
.bar-row .val { font-size: .78rem; text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
.donut-wrap { display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap; }
.legend { list-style: none; padding: 0; margin: 0; font-size: .85rem; }
.legend li { display: flex; align-items: center; gap: .5rem; margin: .3rem 0; }
.swatch { width: .8rem; height: .8rem; border-radius: 3px; display: inline-block; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: .88rem; }
th, td { text-align: left; padding: .55rem .65rem; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--faint); font-weight: 600; text-transform: uppercase; font-size: .68rem; letter-spacing: .04em; }
td.content { max-width: 28rem; }
.tag { display: inline-block; background: var(--panel-2); border: 1px solid var(--border); border-radius: 999px; padding: .1rem .5rem; margin: 0 .2rem .2rem 0; font-size: .75rem; }
.unavailable { color: var(--warn); background: var(--warn-soft); border: 1px solid color-mix(in oklch, var(--warn) 35%, transparent); border-radius: .625rem; padding: .65rem .9rem; font-size: .88rem; }
.foot { max-width: 68rem; margin: 2rem auto 0; color: var(--faint); font-size: .8rem; }
@media (max-width: 640px) {
  .bar-row { grid-template-columns: 5rem 1fr 2rem; }
}
"""


def _is_err(value: Any) -> bool:
    return isinstance(value, BaseException)


def _trunc(text: str, length: int = 180) -> str:
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1] + "\u2026"


def _fmt_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str) and value:
        return value[:16].replace("T", " ")
    return "\u2014"


def _unavailable(reason: Any = None) -> str:
    msg = "unavailable"
    if reason is not None:
        msg = f"unavailable ({escape(str(reason))})"
    return f'<div class="unavailable">{msg}</div>'


def _stat_card(label: str, value: Any, sub: str = "") -> str:
    sub_html = f'<div class="sub">{escape(sub)}</div>' if sub else ""
    return (
        '<div class="card">'
        f'<div class="num">{escape(str(value))}</div>'
        f'<div class="label">{escape(label)}</div>'
        f"{sub_html}</div>"
    )


def _bar_chart(items: list[tuple[str, int]]) -> str:
    if not items:
        return '<p class="muted">No data yet.</p>'
    top = max((count for _, count in items), default=1) or 1
    rows = []
    for i, (name, count) in enumerate(items):
        width = max(2, round(count / top * 100))
        color = _PALETTE[i % len(_PALETTE)]
        rows.append(
            '<div class="bar-row">'
            f'<span class="name" title="{escape(name)}">{escape(name)}</span>'
            f'<span class="track"><span class="fill" style="width:{width}%;background:{color}"></span></span>'
            f'<span class="val">{count}</span>'
            "</div>"
        )
    return "".join(rows)


def _donut_svg(segments: list[tuple[str, int]]) -> str:
    total = sum(v for _, v in segments)
    radius = 60
    cx = cy = 80
    stroke = 28
    circ = 2 * math.pi * radius
    arcs: list[str] = []
    legend: list[str] = []
    offset = 0.0
    denom = total or 1
    for i, (label, value) in enumerate(segments):
        color = _PALETTE[i % len(_PALETTE)]
        frac = value / denom
        dash = frac * circ
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})" />'
        )
        offset += dash
        legend.append(
            f'<li><span class="swatch" style="background:{color}"></span>'
            f"{escape(label)} <strong>&nbsp;{value}</strong></li>"
        )
    ring = (
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#eef0f6" stroke-width="{stroke}" />'
        if total == 0
        else ""
    )
    svg = (
        f'<svg width="160" height="160" viewBox="0 0 160 160" role="img" aria-label="memory distribution">'
        f"{ring}{''.join(arcs)}"
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="26" font-weight="700" fill="#1f2330">{total}</text>'
        f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" font-size="11" fill="#6b7280">records</text>'
        "</svg>"
    )
    return f'<div class="donut-wrap">{svg}<ul class="legend">{"".join(legend)}</ul></div>'


def _records_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="muted">No records yet.</p>'
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(cells) + "</tr>" for cells in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _semantic_record_rows(records: Any) -> list[list[str]]:
    if _is_err(records) or not isinstance(records, list):
        return []
    rows: list[list[str]] = []
    for rec in records:
        if not isinstance(rec, MemoryRecord):
            continue
        content = escape(_trunc(rec.content))
        agent = escape(rec.agent or _DASH)
        kind = escape(rec.kind or _DASH)
        created = escape(_fmt_dt(rec.created_at))
        rows.append(
            [
                f'<td class="content">{content}</td>',
                f"<td>{agent}</td>",
                f"<td>{kind}</td>",
                f"<td>{created}</td>",
            ]
        )
    return rows


def _procedure_rows(procs: Any) -> list[list[str]]:
    if _is_err(procs) or not isinstance(procs, list):
        return []
    rows: list[list[str]] = []
    for p in procs:
        tag_list = p.get("tags") or []
        tags = "".join(f'<span class="tag">{escape(str(t))}</span>' for t in tag_list)
        name = escape(str(p.get("name", "")))
        version = escape(str(p.get("version", "")))
        author = escape(str(p.get("created_by") or _DASH))
        created = escape(_fmt_dt(p.get("created_at")))
        rows.append(
            [
                f"<td>{name}</td>",
                f"<td>v{version}</td>",
                f"<td>{author}</td>",
                f"<td>{tags or _DASH}</td>",
                f"<td>{created}</td>",
            ]
        )
    return rows


def _session_rows(working: Any) -> list[list[str]]:
    if _is_err(working) or not isinstance(working, dict):
        return []
    rows: list[list[str]] = []
    for s in working.get("recent", []):
        status = "closed" if s.get("closed_at") else "active"
        agent = escape(str(s.get("agent") or _DASH))
        topic = escape(_trunc(str(s.get("topic") or _DASH), 80))
        turns = escape(str(s.get("turn_count", 0)))
        opened = escape(_fmt_dt(s.get("opened_at")))
        rows.append(
            [
                f"<td>{agent}</td>",
                f'<td class="content">{topic}</td>',
                f"<td>{turns}</td>",
                f"<td>{escape(status)}</td>",
                f"<td>{opened}</td>",
            ]
        )
    return rows


def _health_badges(health: Any) -> str:
    if _is_err(health) or not isinstance(health, dict):
        return '<span class="badge"><span class="dot bad"></span>status unknown</span>'
    overall = health.get("status", "unknown")
    overall_dot = "ok" if overall == "ok" else "warn"
    badges = [f'<span class="badge"><span class="dot {overall_dot}"></span>{escape(str(overall))}</span>']
    for name, value in (health.get("components") or {}).items():
        text = str(value)
        if text == "ok" or text.startswith("ok "):
            dot = "ok"
        elif text in ("not_ready", "disabled"):
            dot = "warn"
        else:
            dot = "bad"
        badges.append(
            f'<span class="badge"><span class="dot {dot}"></span>{escape(str(name))}: {escape(str(value))}</span>'
        )
    return f'<div class="badges">{"".join(badges)}</div>'


_CONTENT_NOTE = (
    '<p class="muted">Recent memory rows are hidden on the public dashboard. '
    "Sign in at <a href=\"/app\">/app</a> or enable "
    "<code>TEAMSHARED_DASHBOARD_PUBLIC_CONTENT</code> in development.</p>"
)


def _render_page(
    *,
    health: Any,
    working: Any,
    semantic: Any,
    procedural: Any,
    recent_semantic: Any,
    recent_episodic: Any,
    recent_procs: Any,
    show_content: bool,
) -> str:
    w_active = working.get("active", 0) if isinstance(working, dict) else 0
    w_total = working.get("total", 0) if isinstance(working, dict) else 0
    s_count = semantic.get("semantic", 0) if isinstance(semantic, dict) else "\u2014"
    e_count = semantic.get("episodic", 0) if isinstance(semantic, dict) else "\u2014"
    p_count = procedural.get("playbooks", 0) if isinstance(procedural, dict) else "\u2014"
    p_versions = procedural.get("versions", 0) if isinstance(procedural, dict) else 0

    cards = "".join(
        [
            _stat_card("Working sessions", w_active, f"{w_total} in Redis (active + closed)"),
            _stat_card("Semantic", s_count, "facts, preferences, notes"),
            _stat_card("Episodic", e_count, "distilled sessions + events"),
            _stat_card("Procedural", p_count, f"{p_versions} total versions"),
        ]
    )

    donut_segments = [
        ("Working", w_active),
        ("Semantic", semantic.get("semantic", 0) if isinstance(semantic, dict) else 0),
        ("Episodic", semantic.get("episodic", 0) if isinstance(semantic, dict) else 0),
        ("Procedural", p_count if isinstance(p_count, int) else 0),
    ]

    if _is_err(semantic):
        agents_panel = _unavailable(semantic)
        kinds_panel = _unavailable(semantic)
    else:
        by_agent = sorted(semantic.get("by_agent", {}).items(), key=lambda kv: kv[1], reverse=True)
        by_kind = sorted(semantic.get("by_kind", {}).items(), key=lambda kv: kv[1], reverse=True)
        agents_panel = _bar_chart(by_agent)
        kinds_panel = _bar_chart(by_kind)

    if show_content:
        sem_table = (
            _unavailable(recent_semantic)
            if _is_err(recent_semantic)
            else _records_table(
                ["Content", "Agent", "Kind", "Created"], _semantic_record_rows(recent_semantic)
            )
        )
        epi_table = (
            _unavailable(recent_episodic)
            if _is_err(recent_episodic)
            else _records_table(
                ["Content", "Agent", "Kind", "Created"], _semantic_record_rows(recent_episodic)
            )
        )
        proc_table = (
            _unavailable(recent_procs)
            if _is_err(recent_procs)
            else _records_table(
                ["Name", "Version", "Author", "Tags", "Created"], _procedure_rows(recent_procs)
            )
        )
        sess_table = (
            _unavailable(working)
            if _is_err(working)
            else _records_table(
                ["Agent", "Topic", "Turns", "Status", "Opened"], _session_rows(working)
            )
        )
        recent_sections = f"""
    <h2>Recent semantic</h2>
    <div class="panel">{sem_table}</div>

    <h2>Recent episodic</h2>
    <div class="panel">{epi_table}</div>

    <h2>Procedures (playbooks)</h2>
    <div class="panel">{proc_table}</div>

    <h2>Recent working sessions</h2>
    <div class="panel">{sess_table}</div>"""
    else:
        recent_sections = f"""
    <h2>Recent activity</h2>
    <div class="panel">{_CONTENT_NOTE}</div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex" />
  <link rel="icon" href="/favicon.ico" sizes="any" />
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/favicon-32.png" />
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400..700;1,400..700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400..700;1,8..60,400..700&display=swap" rel="stylesheet" />
  <title>teamshared — memory status</title>
  <style>{_DASHBOARD_CSS}</style>
</head>
<body>
  <div class="bar-wrap">
    <h1>teamshared memory status</h1>
    <p class="muted">Shared brain across the team. <a href="/">Home</a> &middot; <a href="/app">Team console</a> &middot; <a href="/app/keys">API keys</a></p>
    {_health_badges(health)}

    <h2>Overview</h2>
    <div class="cards">{cards}</div>

    <h2>Distribution &amp; breakdowns</h2>
    <div class="grid2">
      <div class="panel"><h3>Memory distribution</h3>{_donut_svg(donut_segments)}</div>
      <div class="panel"><h3>Durable memory by agent</h3>{agents_panel}</div>
      <div class="panel"><h3>Semantic kinds</h3>{kinds_panel}</div>
    </div>

{recent_sections}
  </div>
  <p class="foot">Aggregate counts from pgvector, procedures, and Redis; not a full recall index.</p>
</body>
</html>"""


async def handle_memory_dashboard(request: Request, state: ServerState) -> HTMLResponse:
    """Render the public memory status dashboard.

    All store calls run concurrently and tolerate failure: a down backend
    renders an "unavailable" section instead of failing the whole page.
    """
    org_id = state.settings.default_org_id
    core: list[Any] = await asyncio.gather(
        check_components(state),
        state.working.stats(org_id),
        state.services.vector_store.pillar_stats(org_id),
        state.procedural.stats(org_id),
        return_exceptions=True,
    )
    health, working, semantic, procedural = core
    show_content = state.settings.dashboard_public_content
    recent_semantic: Any = []
    recent_episodic: Any = []
    recent_procs: Any = []
    if show_content:
        recent = await asyncio.gather(
            state.services.vector_store.list_recent(org_id, limit=10, pillar="semantic"),
            state.services.vector_store.list_recent(org_id, limit=10, pillar="episodic"),
            state.procedural.list_procedures(org_id, limit=10),
            return_exceptions=True,
        )
        recent_semantic, recent_episodic, recent_procs = recent
    page = _render_page(
        health=health,
        working=working,
        semantic=semantic,
        procedural=procedural,
        recent_semantic=recent_semantic,
        recent_episodic=recent_episodic,
        recent_procs=recent_procs,
        show_content=show_content,
    )
    return HTMLResponse(page)
