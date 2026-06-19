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
user research — the graph reflects that honestly.

It also includes one **external market signal**: `company-brain-yc-rfs.md` (Tom
Blomfield's "Company Brain" YC Request for Startups). That is a directional
vision bet, *still not* user evidence. Add interviews, tickets, and support
threads here to move the corpus from "thin" toward "rich".
