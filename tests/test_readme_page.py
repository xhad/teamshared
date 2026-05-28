"""README rendering for token onboarding pages."""

from __future__ import annotations

from teamshared.clients.readme_page import load_readme_md, render_readme_html


def test_load_readme_md_contains_title() -> None:
    md = load_readme_md()
    assert md.startswith("# teamshared")
    assert "Multi-pillar agent memory" in md


def test_render_readme_html_includes_structure() -> None:
    html = render_readme_html()
    assert 'id="about-teamshared"' in html
    assert "About teamshared" in html
    assert "teamshared" in html
    assert "memory_recall" in html
    assert "<table>" in html
