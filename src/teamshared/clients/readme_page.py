"""Load and render bundled README.md for token onboarding pages."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import markdown

_REPO_README = Path(__file__).resolve().parents[3] / "README.md"

_README_CSS = """
.readme {
  margin-top: 2.5rem;
  padding-top: 2rem;
  border-top: 1px solid #e4e4e7;
}
.readme h1, .readme h2, .readme h3 { margin-top: 1.75rem; margin-bottom: 0.75rem; line-height: 1.25; }
.readme h1 { font-size: 1.5rem; }
.readme h2 { font-size: 1.25rem; }
.readme p, .readme li { color: #3f3f46; }
.readme pre {
  background: #f4f4f5;
  padding: 0.75rem 1rem;
  overflow-x: auto;
  border-radius: 0.375rem;
  font-size: 0.875rem;
}
.readme code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.875em; }
.readme :not(pre) > code { background: #f4f4f5; padding: 0.125rem 0.375rem; border-radius: 0.25rem; }
.readme table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.925rem; }
.readme th, .readme td { border: 1px solid #e4e4e7; padding: 0.5rem 0.75rem; text-align: left; }
.readme th { background: #fafafa; font-weight: 600; }
.readme ul, .readme ol { padding-left: 1.5rem; }
.readme a { color: #2563eb; }
.readme blockquote {
  margin: 1rem 0;
  padding-left: 1rem;
  border-left: 3px solid #d4d4d8;
  color: #52525b;
}
"""


def load_readme_md() -> str:
    """Return README markdown bundled with the package (dev fallback: repo root)."""
    try:
        raw = resources.files("teamshared.clients").joinpath("README.md").read_bytes()
        return raw.decode("utf-8")
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        if _REPO_README.is_file():
            return _REPO_README.read_text(encoding="utf-8")
        raise FileNotFoundError(
            "README.md is not bundled and repo copy is missing"
        ) from None


def render_readme_html() -> str:
    """Render README.md to an HTML fragment for onboarding pages."""
    body = markdown.markdown(
        load_readme_md(),
        extensions=["fenced_code", "tables", "toc"],
        output_format="html",
    )
    return f"""<style>{_README_CSS}</style>
<section class="readme" id="about-teamshared">
  <h2>About teamshared</h2>
  <p class="readme-intro">Shared memory for your agents — what it is, how the pillars work, and the MCP tools available.</p>
  {body}
</section>"""
