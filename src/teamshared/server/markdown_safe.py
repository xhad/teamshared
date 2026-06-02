"""Render untrusted markdown to a safe HTML fragment.

Wiki bodies (procedural ``steps_md``, future curated pages) originate from agent
input, so rendering them as raw HTML would be an XSS vector. We render markdown
with the same extensions as the trusted README path, then run the output through
an allowlist sanitizer built on :class:`html.parser.HTMLParser`: only known-safe
tags/attributes survive, every other tag is dropped, text is escaped, and link
targets are restricted to safe URL schemes. The result is marked safe for Jinja.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

import markdown as _markdown

# Tags we emit verbatim. Anything else (script, style, iframe, ...) is dropped.
_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "strong", "em", "b", "i", "u", "del", "sup", "sub",
        "code", "pre", "blockquote", "span",
        "ul", "ol", "li", "a",
        "table", "thead", "tbody", "tr", "th", "td",
    }
)
# Per-tag attribute allowlist. Attributes not listed (incl. on* handlers) drop.
_ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "th": frozenset({"align"}),
    "td": frozenset({"align"}),
}
# Void tags never get a closing tag emitted.
_VOID_TAGS: frozenset[str] = frozenset({"br", "hr"})
# Only these URL schemes (or relative/anchor links) are allowed in href.
_SAFE_URL = re.compile(r"^(?:https?:|mailto:|#|/|\./)", re.IGNORECASE)


class _Sanitizer(HTMLParser):
    """Rebuild an HTML string from only allowlisted tags, attrs, and text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []

    def _emit_open(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _ALLOWED_TAGS:
            return
        allowed = _ALLOWED_ATTRS.get(tag, frozenset())
        kept: list[str] = []
        for key, value in attrs:
            if key not in allowed:
                continue
            val = value or ""
            if key == "href" and not _SAFE_URL.match(val.strip()):
                continue
            kept.append(f' {key}="{escape(val, quote=True)}"')
        self._out.append(f"<{tag}{''.join(kept)}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._emit_open(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._emit_open(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._out.append(escape(data))

    def result(self) -> str:
        return "".join(self._out)


def sanitize_html(html: str) -> str:
    """Drop everything not on the tag/attribute allowlist; escape all text."""
    parser = _Sanitizer()
    parser.feed(html)
    parser.close()
    return parser.result()


def render_markdown_safe(text: str) -> str:
    """Markdown -> sanitized HTML fragment safe to render in the console."""
    raw = _markdown.markdown(
        text or "", extensions=["fenced_code", "tables"], output_format="html5"
    )
    return sanitize_html(raw)
