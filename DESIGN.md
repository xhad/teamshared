# TeamShared — Design system

Product register. Dark-only admin console. Tokens live in `src/teamshared/server/static/console.css`; public `/memory` dashboard mirrors the same palette inline.

## Principles

1. **Information first** — task before decoration.
2. **Responsive parity** — drawer nav + scrollable tables on mobile.
3. **Cohesive dark theme** — deep space bg, indigo accent.
4. **Accessible contrast** — WCAG AA body text; focus rings on all controls.
5. **Consistent tokens** — no hard-coded hex in templates.

## Color tokens

| Token | Role |
|-------|------|
| `--bg`, `--bg-soft`, `--bg-elevated` | Page and chrome surfaces |
| `--panel`, `--panel-2` | Cards, tables, inputs |
| `--text`, `--muted`, `--faint` | Ink hierarchy |
| `--accent`, `--accent-bright`, `--accent-soft`, `--accent-ring` | Primary actions, selection, links |
| `--success`, `--success-soft` | Completed / active-positive state (green) |
| `--danger`, `--danger-soft` | Errors, blocked, destructive |
| `--warn`, `--warn-soft` | Warnings, unavailable, pending |

**Accent** is indigo brand color. **Success** is semantic green — never reuse accent for “done”.

## Typography

- Stack: system sans (`--font-sans`); mono for code (`--font-mono`).
- Body: `clamp(0.9rem … 1rem)`, line-height 1.55, max ~65ch in prose.
- Headings: `text-wrap: balance` on h1–h3.
- Labels: uppercase micro labels in forms (`.field > label`).

## Layout

- Shell: fixed sidebar (desktop) / slide-out drawer (≤768px).
- Content max-width: `72rem`.
- Spacing scale: `0.25 0.5 0.75 1 1.25 1.5 1.75 2` rem utilities (`.gap-*`).

## Components

| Class | Use |
|-------|-----|
| `.panel` | Primary content surface |
| `.page-head` | Title + actions row |
| `.stats-row` / `.stat` | Home overview metrics |
| `.catalog-search` | Filterable list pages (skills, playbooks) |
| `.catalog-card` | Searchable card in catalog lists |
| `.flash-ok` / `.flash-pending` / `.unavailable` | Feedback banners |
| `dialog.modal` | Inline propose/edit flows |
| `.nested-block` | Indented related content (no side-stripe borders) |
| `.empty-state` | Teach the interface when lists are empty |
| `.entity-kv` | Ontology entity property grid |

## Motion

- Easing: `--ease-out` (cubic-bezier 0.22, 1, 0.36, 1).
- Transitions: 150ms on hover/focus; drawer 250ms.
- `prefers-reduced-motion: reduce` zeroes transitions globally.

## Navigation IA

Grouped sidebar:

- **Overview** — Home
- **Memory** — Wiki, Playbooks, Skills, Memory explorer
- **Work** — Work, Projects, Strategy
- **Admin** — People, Orgs, API Keys, Audit, Settings

## Banned patterns

Per `.impeccable.md` and Impeccable product register:

- Side-stripe accent borders on list items
- Hard-coded `#fff` / `#fcd34d` in templates
- Duplicate per-page `<style>` blocks for shared patterns
- Using `--accent` for success/done states
