# TeamShared — Product context

## What it is

TeamShared is a shared memory MCP server for engineering teams and their agents. Humans administer the brain through a web console (`/app`); agents read and write through bearer-token MCP tools.

## Register

**Product** — design serves the task. This is an admin console and knowledge workspace, not a marketing site.

## Users

Engineering leads, developers, and ops teammates who:

- Review wiki topics and entity rollups
- Triage the work queue and approvals
- Mint API keys and manage org membership
- Inspect memory, agents, and audit trails

Often on a laptop; sometimes on a phone between meetings.

## Jobs to be done

1. **Orient** — see brain health, open work, and recent activity at a glance (Home).
2. **Know** — browse wiki, skills, playbooks, and memory explorer.
3. **Act** — create/update work, approve agent writes, assign agents.
4. **Govern** — people, orgs, keys, consent, audit.

## Surfaces

| Surface | Audience | Notes |
|---------|----------|-------|
| `/app/*` console | Authenticated humans | Primary product UI; dark-only |
| `/login` | Humans | OTP sign-in |
| `/memory` | Public | Status dashboard; zero-JS |
| `/install` | Humans | Onboarding |

## Quality bar

**Flagship admin tool** — earned familiarity (Linear/Notion/Stripe bar). Consistency screen-to-screen beats decorative surprise. Information density where it matters.

## Non-goals

- Light mode
- Consumer/playful AI-demo aesthetic
- Marketing-heavy landing inside the console shell

## Design source of truth

- `.impeccable.md` — brand personality and anti-references
- `DESIGN.md` — tokens, components, and patterns (generated from `console.css`)
