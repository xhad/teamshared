"""Allowlist HTML sanitizer for wiki markdown bodies.

Pins the XSS guard the design flags as a hard risk: agent-authored markdown
(procedural ``steps_md``, future curated pages) must never render executable or
otherwise dangerous HTML.
"""

from __future__ import annotations

from teamshared.server.markdown_safe import render_markdown_safe, sanitize_html


def test_basic_markdown_renders() -> None:
    out = render_markdown_safe("A **bold** and _em_ word.")
    assert "<strong>bold</strong>" in out
    assert "<em>em</em>" in out


def test_script_tag_is_dropped() -> None:
    out = render_markdown_safe("ok\n\n<script>alert(1)</script>")
    assert "<script" not in out
    # the tag is gone; its text content is escaped, never executable
    assert "alert(1)" in out


def test_javascript_href_is_stripped() -> None:
    out = render_markdown_safe("[click](javascript:alert(1))")
    assert "javascript:" not in out
    assert "<a" in out  # the anchor survives, just without the unsafe href


def test_safe_https_href_survives() -> None:
    out = render_markdown_safe("[site](https://example.com)")
    assert 'href="https://example.com"' in out


def test_event_handler_and_unknown_tags_are_removed() -> None:
    out = sanitize_html('<img src=x onerror="alert(1)"><b>keep</b>')
    assert "<img" not in out
    assert "onerror" not in out
    assert "<b>keep</b>" in out


def test_tables_and_code_render() -> None:
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```"
    out = render_markdown_safe(md)
    assert "<table>" in out
    assert "<pre>" in out


def test_empty_input_is_safe() -> None:
    assert render_markdown_safe("") == ""
