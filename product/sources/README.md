# sources/

Drop raw research here — one file per artifact. `graphify` reads every file in
this folder (skipping this README) and builds an evidence graph.

Give each file YAML frontmatter so the graph can classify it:

```md
---
type: interview   # interview | ticket | prd | memo | research | transcript | note | other
---
```

This workspace is currently seeded with the internal TeamShared planning docs
(symlinked from the repo root): `prod-plan.md`, `plan.md`, `memory-wiki-plan.md`,
`teamshared-readme.md`, `teamshared-agents.md`. These are **product intent**, not
user research — the graph reflects that honestly. Add interviews, tickets, and
support threads here to move the corpus from "thin" toward "rich".
