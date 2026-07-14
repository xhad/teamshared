---
type: research
title: "PromptQL — competitor landscape research"
author: Hasura, Inc. / PromptQL
origin: https://promptql.io/en/docs
captured: 2026-07-13
note: >
  External competitor research from PromptQL's public documentation homepage.
  Product marketing claims only — no user research. Treat as single-source
  competitive intelligence.
---

# PromptQL competitor research

Captured 2026-07-13 from [promptql.io/en/docs](https://promptql.io/en/docs).
PromptQL is a Hasura-backed product that positions itself as a
**multiplayer AI for your team that maintains a shared context wiki**.

## Positioning

> PromptQL helps you build a multiplayer AI for your team that maintains a shared context wiki.

> 1. Plug in your data and context sources, set up security and authorization rules.
> 2. Onboard your team so that they can use it via the PromptQL app or as an AI agent within Slack/Teams.

> PromptQL provides all the infrastructure for running a multiplayer coworker, including a secure coding environment in the cloud for the AI to write and run code in to solve problems, without leaking credentials or resulting in privilege escalation.

> PromptQL is entirely self-documenting and self-configurable (safely).

## Surfaces / distribution

> | Surface | Action |
> | Web | Sign in at prompt.ql.app |
> | Desktop | Mac (Apple Silicon), Mac (Intel), Windows |
> | Mobile | iOS beta, Android beta |
> | Slack | Open in Slack |

## Connectors and data access

> Connect databases (Postgres, Snowflake, BigQuery, Databricks, and more) and SaaS integrations (GitHub, Slack, Salesforce, Google Workspace, and many others).

> PromptQL queries data where it lives — no copying into a warehouse, no ETL pipelines to build — with per-user permissions enforced at the data layer.

## Artifacts and query UX

> Ask in plain language and get back artifacts — tables, charts, reports, and interactive dashboards — that you can share and act on. PromptQL writes and runs the queries and code for you.

## Multiplayer collaboration

> PromptQL is multiplayer. Multiple people can join the same thread, @-mention each other and the agent, and collaborate in real time. The context that makes AI accurate is captured into a shared wiki as you work.

## Shared brain / wiki

> As your team works with PromptQL, the wiki captures domain knowledge, tribal context, and business definitions — so the agent gets smarter over time and every teammate benefits from shared context.

## Delegation to coding agents

> Connect coding agents like Claude Code or Codex running on your own machines. PromptQL can delegate code investigation, feature development, and browser testing tasks securely.

## Competitive overlap with TeamShared (analyst notes — not PromptQL claims)

PromptQL and TeamShared both target **shared institutional context for AI-assisted teams**, but PromptQL is pitched as a data+BI multiplayer agent with a wiki side effect, whereas TeamShared is pitched as memory infrastructure for agents. Overlap surfaces:

| Dimension | PromptQL (public claims) | TeamShared (internal plan) |
|---|---|---|
| Primary shape | Multiplayer AI analyst over live data + shared wiki | Multi-tenant agent memory server with five pillars |
| Distribution | Web app, desktop, mobile, Slack agent | MCP server + Cursor plugin + web console |
| Data connectors | Postgres, Snowflake, BigQuery, Databricks, GitHub, Slack, Salesforce, GWorkspace, etc. | Server-side conversation capture, optional connectors |
| Permissions | Per-user permissions enforced at the data layer | RLS, RBAC, org isolation, approval queue |
| Query UX | Plain language → artifacts (tables, charts, dashboards) | `memory_recall` records, `memory_think` synthesis, curated wiki |
| Collaboration | Real-time multiplayer thread with @-mentions | Asynchronous work queue, org-scoped memory |
| Coding agents | Delegates to Claude Code / Codex on user's machine | MCP-native for any harness; no sandboxed cloud coding environment |
| Memory model | Shared wiki as a side effect of collaboration | First-class semantic/episodic/procedural/skill/strategic/work taxonomy |
| Capture | Connector-driven data + chat context | Server-side `ToolCallCaptureMiddleware`, `capture_enabled` flag |

## Gaps PromptQL docs do NOT emphasize (relative to TeamShared plan)

- No explicit **agent-facing memory tools** (MCP or otherwise) — the agent is the PromptQL product, not a memory substrate other agents can call.
- No **five-pillar memory taxonomy** (working/semantic/episodic/procedural/strategic/work).
- No **work queue** or **strategic OKRs** as first-class surfaces.
- No **agent attribution / approval queue** for durable writes called out.
- No **open-source or self-host** narrative; appears to be a hosted Hasura SaaS.

## Threat level signals

- **Backing**: Hasura, Inc. (established data/GraphQL infrastructure company).
- **Category framing**: "multiplayer AI" and "shared context wiki" directly overlaps TeamShared's "shared brain" positioning.
- **Data-live moat**: "queries data where it lives" with per-user permissions is a genuine differentiator TeamShared does not yet claim.
- **Agent delegation**: Can hand off coding tasks to Claude Code/Codex — adjacent to the harness-agnostic capture TeamShared wants to enable.

---

# PromptQL deep dive (product + security pages)

Captured 2026-07-13 from [promptql.io](https://promptql.io) homepage, [product](https://promptql.io/product), and [security](https://promptql.io/security) pages.

## Product thesis

> Maintaining context is the second job nobody wants. So PromptQL does it. It's a multiplayer AI agent — think Claude or ChatGPT, but with shared threads and a shared brain. Point it at the context you already have. Correct it once and it sticks — for everyone.

> Your AI workspace to discuss, decide, and act. PromptQL connects to data wherever it lives and writes code to answer real business questions. It captures your team's shared context from everyday conversations, continuously improving accuracy.

## Core capabilities (product page)

### 1. Connect any data, any context. No prep needed.
- Connect warehouse, databases, SaaS apps, and APIs as they exist today.
- PromptQL introspects schemas to build a unified data graph, without moving or reshaping data.
- Seed business context from Slack, Google Drive, GitHub, wherever knowledge already lives. No semantic layer required on day one.

### 2. One stop for all your data questions
- Simple to complex: descriptive questions to multi-source, multi-hop deep investigations.
- Every question gets a well-reasoned answer with sources and assumptions shown.
- Generate board-ready dashboards and reports, automatically aligned with brand style and audience.
- Turn recurring workflows into reusable artifacts for the team.

### 3. Semantic layer / Operational wiki → AI accuracy
- Traditional semantic layers are rigid and centrally managed; PromptQL uses a dynamic, Wikipedia-style context graph.
- Multiplayer by design: teammates join threads to review, clarify, correct, and refine.
- Teachable in the flow: corrections and decisions become durable, shared understanding without documentation overhead.
- Keeps analysis in open channels and shared threads; private threads or restricted channels for sensitive analysis.

## How to use it / workflows (homepage examples)

### Example 1: Churn-risk question in a shared thread
1. Maya asks in a shared thread: "Acme renews in 3 weeks. Are they a churn risk?"
2. PromptQL analyzes usage data and support ticket sentiment, showing its work (sources pulled, assumptions made).
3. It surfaces a conclusion: "Yes — a risk."
4. Sam adds context: "It's the month-end Friday export lag. Not a product problem."
5. PromptQL proposes a wiki update: "Acme's usage dips ~10% every month-end because of a known Friday export lag — it is not a churn signal."
6. The team reviews and clicks "Add to wiki"; the correction becomes durable, cited knowledge for future sessions.

### Example 2: Seed the wiki in 60 seconds
1. User asks: "Seed the wiki for AcmeCorp."
2. PromptQL reads from Slack, Google Docs, Snowflake, PostHog, Salesforce CRM.
3. It creates 7 wiki pages automatically.

### Example 3: Suggest context updates as people work
1. Dana asks: "Pull Q1 revenue by region for the board deck."
2. PromptQL assumes revenue = analytics.revenue and returns a table.
3. Dana corrects: "That table's stale — revenue moved to netsuite.revenue last quarter."
4. PromptQL re-pulls from netsuite.revenue and proposes a wiki update: "Revenue · source is netsuite.revenue, not analytics.revenue (stale since Q4 2025)."
5. Dana adds it to the wiki.

### Example 4: Wikipedia-like operating model
- Easy for non-technical and technical users.
- Citations to real work.
- Revision history, audit trails & editorial controls.
- Notifications on changes, page creations, and deletions.

### Example 5: Govern with scopes
- One shared wiki, with different connected neighborhoods visible to each scope.
- Example scopes: Customer: AcmeCorp, Internal, Personal: Sara, Confidential: Finance.
- Granular view & edit control; bulk operations for rapid changes.

## Security model (security page)

### Core principle: The AI inherits a real user identity
- No shared login. The AI inherits the user's identity, enforced to fetch the right context and reach the right data & tools — deterministically, in a way the AI cannot circumvent.
- Every action runs as the person who asked — their credentials, their permissions, their data. Same thread, two people, two different answers.
- Permissions enforced at the data layer, not by the model, so prompt injection cannot bypass them.
- Writes & external calls require approval with a plain-language summary.
- Credentials injected at runtime; never exposed to the model or other users.
- Nothing ever runs as "the AI." Every action traces to a real human.

### Infrastructure: BYOC (Bring Your Own Cloud)
- Split control plane / data plane.
- Data plane (customer-owned AWS/GCP/Azure): conversation history, wiki & knowledge base, metadata & indexes, credentials & secrets.
- Control plane (Hasura-hosted): auth, billing, observability, version/update delivery.
- Private connectivity: AWS PrivateLink, GCP Private Service Connect, Azure Private Endpoint.

### AI Sandboxing
- Virtual SQL Layer: all data sources unified behind a virtual SQL interface. AI issues standard SQL; layer enforces RLS, column masks, ABAC claims before data is touched. No raw DB credentials exposed to AI.
- Sandboxed HTTP: outbound AI requests routed through sandboxed API access layer. OAuth tokens injected server-side; domain allowlists and rate limits enforced.
- Computer Agents (SCAS): Browser/desktop agents connect through Secure Computer Agent Service. Personal agents only accessible to creator; shared agents admin-configured. Secure tunnels; no open inbound ports.

### Supply Chain Security
- Python code runs in a WebAssembly sandbox with fixed, vetted dependency list (numpy, pandas, openpyxl, reportlab). No pip install at runtime.
- Enterprise customers can request reviewed custom dependency lists.
- Sandbox structurally isolated: no host filesystem, network, or system-call access.

### Authorization layers
1. **Data Authorization**: RLS, column restrictions, ABAC (JWT claims), custom claims.
2. **API Integration Authorization**: personal OAuth, shared OAuth, API key management, scope enforcement.
3. **Computer Agent Authorization**: personal/shared agent boundaries, session-scoped keys, secure tunnels, audit trail.

### Audit logs
- SQL Query Audit, LLM Usage Audit, Wiki Access Audit, HTTP API Call Audit, Computer Agent Action Audit.

### Compliance & Certifications
- SOC 2 Type II, ISO 27001, HIPAA, GDPR, CCPA.

## Connectors detail (docs/connectors)

PromptQL builds connectors on the fly for any service that supports:
1. OAuth2
2. API tokens
3. JDBC (SQL) & MongoDB's data protocol

Users ask PromptQL to help set up a connector, explain security configuration, and configure permissions including row-level security rules for database sources.

## Wiki detail (docs/wiki)

- Designed for accurate maintenance and retrieval at massive scale.
- Each wiki page has optional scopes that grant different user groups read/write ability.
- Users ask PromptQL to help manage scopes and security configuration.

## Users detail (docs/users)

- User directory for internal users, external users, and AI users.
- Manage usage quotas and claims that grant access to the wiki and data sources.

## Embedded use cases (product page)

1. **Internal teams**: technical, business, ops, and executives get instant, trusted answers to business questions.
2. **Customer-facing products**: embed PromptQL under your brand so customers can explore their own data.
3. **Agents & automation**: call PromptQL from other agents for trusted analytics, retrieval, and reasoning.

## Distribution surfaces

- Web: prompt.ql.app
- Desktop: Mac (Apple Silicon), Mac (Intel), Windows
- Mobile: iOS App Store, Android (Google Play)
- Slack: via Slack integration
- Customer-facing embed
