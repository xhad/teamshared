# TeamShared Wiki Redesign Plan (mogkit)

Generated via mogkit workflow: `tradeoff-frame` on the current `/app/wiki` + a
shallow audit of the shipped code. The user asked: *the current wiki page is
useless; either remove it or make it a human-readable area similar to Obsidian.*

---

## Current state diagnosis

`/app/wiki` today is a server-rendered Jinja2 surface with three tabs:

- **Topics** (`/app/wiki`) — tag cloud, subject list, and a "recently updated"
  table of raw semantic records.
- **Topic page** (`/app/wiki/topic/{slug}`) — a curated article if the curator
  worker has produced one, otherwise a list of raw source records grouped by
  `kind`.
- **Timeline** (`/app/wiki/timeline`) — reverse-chronological raw episodic
  entries.

Behind the scenes:
- `WikiStore` persists versioned markdown in `wiki_pages`.
- `CuratorWorker` synthesizes `body_md` from a subject's facts + episodes via
  `teamshared.distill.curator.curate`.
- `markdown_safe.render_markdown_safe` renders the curated markdown using only
  `fenced_code` and `tables` extensions, then allowlist-sanitizes the HTML.

### Why it feels useless

1. **No human editing.** Curated pages are read-only; the only way to improve a
   page is to change the underlying memory and wait for a re-curation.
2. **No linking.** `[[WikiLink]]` syntax is not parsed, so pages do not connect
   into a browsable graph. The "shared brain" promise is visually absent.
3. **Raw-record dump dominates.** When curation has not run or is poor, the page
   falls back to listing source records, which reads like a database table.
4. **No search.** The wiki home has no search input; navigation is only by tag
   or subject list.
5. **Markdown is under-rendered.** No task lists, no strikethrough, no
   footnotes, no wikilinks, no Mermaid/graph view — the page feels plain.
6. **Unclear curation status.** Users cannot see whether a page is stale, what
   version it is, or how to trigger a refresh.

### What works and should be kept

- **Versioned `wiki_pages` store** — the data model is sound.
- **Curator as a background synthesizer** — valuable when it works, but it should
  be an assistant, not the sole author.
- **Sanitized markdown rendering** — security-critical; keep the allowlist
  sanitizer for agent-generated content.
- **RLS/org-scoped store** — stays aligned with the multi-tenant architecture.

---

## tradeoff-frame: What should we do with the wiki?

### The decision

Should TeamShared remove the wiki, rebuild it as a full Obsidian-like knowledge
workspace, or improve it incrementally toward an Obsidian-lite experience?

**Options:**
- **A.** Remove the wiki entirely — redirect `/app/wiki` to `/app/memory` and
  delete the curator/wiki surface.
- **B.** Full Obsidian rebuild — bidirectional wikilinks, live markdown
  editor, graph view, daily notes, plugins, folders, and local-first sync.
- **C.** Obsidian-lite incremental rebuild — keep the existing data model but add
  human editing, wikilinks, backlinks, search, daily/timeline notes, and a
  simple graph view.
- **D.** Replace with a "Memory Notebook" — retire auto-curation and make the
  wiki a human-authored notebook over memory records.

### Real axes

1. **Engineering cost** — A is cheap; B is a quarter-or-more project; C is
   weeks-to-a-month; D is similar to C but narrows scope.
2. **User value today** — A removes a dead surface; B/D/C make the wiki useful.
3. **Strategic fit** — The wiki is central to the "shared brain" narrative; A
   weakens the product story.
4. **Maintenance burden** — B creates a long-lived surface (editor, sync, graph)
   that needs ongoing polish; C and D are narrower.
5. **Security surface** — Editing introduces XSS/PII risks; B is larger than C.

### Option profiles

**A — Remove the wiki**
- Optimizes: focus, less code to maintain, no embarrassment from a dead page.
- Sacrifices: human-readable memory surface, "shared brain" UX, and a reason for
  non-technical teammates to open the console.
- Reversibility: Hard. Once removed, reintroducing a wiki later is a feature
  re-launch, not a tweak.

**B — Full Obsidian rebuild**
- Optimizes: category-leading human knowledge workspace, backlinks, graph,
  live preview, plugin potential.
- Sacrifices: Large engineering cost; competes with a mature free product
  (Obsidian itself); potential scope creep; security complexity (live editor +
  local sync + graph view).
- Reversibility: One-way. Building it commits TeamShared to maintaining a
  document editor forever.

**C — Obsidian-lite incremental rebuild**
- Optimizes: Fastest path to a useful wiki; builds on existing `wiki_pages` store;
  adds human editing, wikilinks, backlinks, search, and a simple graph view
  without matching Obsidian feature-for-feature.
- Sacrifices: Not as flashy as a full Obsidian clone; still requires curation
  UX work.
- Reversibility: Two-way. Features can ship incrementally and be retired without
  breaking the core memory store.

**D — Memory Notebook**
- Optimizes: Clarifies the wiki as a human-authored layer over raw memory,
  sidesteps the brittle auto-curation problem.
- Sacrifices: Abandons the dream of auto-curated pages; humans must do more
  writing.
- Reversibility: Two-way. Auto-curation can be added back later as a
  suggestion engine.

### Decisive evidence

- A team member (besides the agent) actually opens `/app/wiki` and finds it
  useful today → validates keeping it.
- A user says "I would use the wiki if I could edit it" → validates C or D.
- A user says "I would use the wiki if it had a graph view like Obsidian" →
  validates C or B.
- A user says "I never look at the wiki; I only use the memory tools" →
  validates A.
- The curated pages are consistently poor or stale → validates D or A.

### Unspoken axis

The wiki is the only human-facing surface in the console that shows the *value*
of shared memory. If it stays useless, the console itself becomes "admin only,"
and TeamShared risks being seen as infrastructure for agents rather than a team
product. That is a positioning argument, not a user-evidence argument.

---

## Recommendation: Obsidian-lite incremental rebuild (Option C)

Do not remove the wiki. Do not rebuild it as a full Obsidian clone. Instead,
make the existing wiki editable, linkable, and searchable in small, shippable
steps.

The guiding principle: **humans should be able to correct and connect the wiki,
and agents should be able to suggest updates.** The curator becomes a
suggestion engine, not the sole author.

### Why C over D?

Option C keeps the curator as a first draft generator while adding human
override. Option D throws the curator away. Since the curator is already built
and sometimes useful, it is cheaper to add an edit layer than to replace the
entire authoring model. If human edits prove far more valuable than curation,
Option D can be reached later by de-emphasizing the curator.

---

## Concrete plan

### Phase 1: Make pages editable (highest impact, smallest scope)

1. **Add an edit button on `/app/wiki/topic/{slug}`.**
2. **Add `POST /app/wiki/topic/{slug}/edit`** that writes a new `wiki_pages`
   version with `updated_by = <user email>` and `sources = []` (or the prior
   sources). Reuse `WikiStore.upsert_page`.
3. **Use a plain `<textarea>`** for the markdown editor. No rich-text toolbar
   yet. Keep it server-rendered and HTMX-light.
4. **Render the edit form with a live preview** (optional; can be a second
   render pass). If too complex, skip preview in v1.
5. **Security:** sanitize the submitted markdown with the existing
   `markdown_safe` path before storing? Actually, the markdown should be stored
   raw and sanitized on render. Store raw markdown in `body_md`; render on read.
   Add a permission check (`memory:write` or `org:admin`).
6. **Show version history** on the topic page (already supported by
   `WikiStore.list_versions`).

### Phase 2: Wikilinks + backlinks

1. **Extend `markdown_safe.render_markdown_safe`** to parse `[[Topic]]` and
   `[[Topic|Display Name]]` links.
2. **Resolve wikilinks to `/app/wiki/topic/{slug}`** using the existing
   `slugify` function.
3. **Add a "Linked from" / backlinks panel** on topic pages. Compute backlinks
   by scanning `wiki_pages` bodies for `[[...]]` references (or maintain a
   `wiki_links` table for performance).
4. **Style broken links differently** (link to a "create page" flow) so the
   graph can grow organically.

### Phase 3: Search + navigation

1. **Add a search input on `/app/wiki`.**
2. **Back it with `WikiStore` + full-text search** on `title` and `body_md`.
   (Requires a Postgres `tsvector` index or a simple `ILIKE` fallback.)
3. **Add "Recent changes"** list using `WikiStore.list_pages` sorted by
   `updated_at`.
4. **Add "All pages" alphabetical index**.

### Phase 4: Simple graph view

1. **Add `/app/wiki/graph`.**
2. **Render a lightweight force-directed graph** of wiki pages and their
   wikilink edges using a small inline SVG or D3 (D3 is a single JS dependency;
   acceptable for the console).
3. **Keep it read-only** in v1; clicking a node navigates to the topic page.

### Phase 5: Daily notes / timeline improvements

1. **Add `/app/wiki/today`** or `/app/wiki/daily/{YYYY-MM-DD}`.
2. **Show distilled episodic entries for that date** grouped by subject.
3. **Allow human editing of daily notes**, creating a lightweight journal over
   the episodic timeline.

### Phase 6: Curator as suggestion engine

1. **When the curator produces a new version, mark it as a draft/suggestion**
   rather than immediately overwriting the live page.
2. **Show a "Review curation" prompt** on the topic page with a diff view.
3. **Human approves or edits the suggestion** before it becomes the live
   version.

---

## Suggested database / schema changes

### Minimal changes (phases 1–2)

No schema changes required. Reuse `wiki_pages` columns:
- `updated_by` can store a user email or `curator`.
- `sources` stays as the contributing memory IDs.

Add an index if search becomes slow:

```sql
CREATE INDEX idx_wiki_pages_search ON wiki_pages USING gin (to_tsvector('english', title || ' ' || coalesce(body_md, '')));
```

Consider a `wiki_links` table for fast backlink queries if the wiki grows past
~100 pages:

```sql
CREATE TABLE wiki_links (
  org_id uuid NOT NULL,
  from_slug text NOT NULL,
  to_slug text NOT NULL,
  PRIMARY KEY (org_id, from_slug, to_slug)
);
```

### UI / template changes

- `wiki_topic.html`: add edit button, version history, backlinks panel,
  wikilink-aware rendering.
- `wiki_home.html`: add search, recent changes, all-pages index.
- New `wiki_edit.html`: simple textarea form.
- New `wiki_graph.html`: SVG/D3 graph view.
- `_wiki_tabs.html`: add "Graph" and "Daily" tabs.

### Markdown rendering changes

Extend `render_markdown_safe` in `src/teamshared/server/markdown_safe.py`:

1. Add extensions: `strike`, `nl2br`, `toc` (table of contents), `wikilinks` (custom).
2. Implement a custom `WikiLinkExtension` that transforms `[[...]]` into
   `<a href="/app/wiki/topic/{slug}">...</a>`.
3. Keep the allowlist sanitizer as the final pass.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| XSS from human-edited markdown | Store raw markdown; render through the existing allowlist sanitizer; forbid raw HTML in user input. |
| PII in wiki pages | Apply the same PII/injection detection used for memory ingestion; allow redaction in the editor. |
| Edit conflicts / concurrent edits | Versioned store makes conflicts visible; use optimistic locking or "last write wins" with version history. |
| Curator-generated drafts are ignored | Make drafts prominent but not intrusive; allow one-click approve. |
| Graph view performance | Cap nodes/edges; lazy-load; maintain a `wiki_links` table if needed. |
| Scope creep toward full Obsidian | Keep the roadmap in phases; defer rich-text editor, plugins, and local sync. |

---

## Open questions

1. Who should be allowed to edit wiki pages? All org members, or only
   `org:admin` / `memory:write` holders?
2. Should agent-curated pages be editable by humans, or should human edits
   create a separate "human override" version?
3. Should we support markdown frontmatter (e.g., `tags:`) in wiki pages?
4. Should the graph view be a single dependency (D3) or pure SVG?
5. Do we want to import/export Markdown files so users can sync with Obsidian
   locally? (Phase 7 idea.)

---

## Next step

Ship **Phase 1 (editable topic pages)** first. It is the smallest change that
makes the wiki feel alive, and it unblocks every later phase.

Estimated effort: 1–2 engineering days for Phase 1, plus tests.

## Files touched

- `product/knowledge/wiki-redesign-plan.md` — this document
- `src/teamshared/server/console.py` — new `POST /app/wiki/topic/{slug}/edit` route
- `src/teamshared/server/templates/wiki_topic.html` — edit button + version history
- `src/teamshared/server/templates/wiki_edit.html` — new edit form
- `src/teamshared/server/markdown_safe.py` — wikilink extension (Phase 2)
- `src/teamshared/memory/wiki.py` — optional search helper / backlink helper
- `tests/test_console.py` — edit-route tests
