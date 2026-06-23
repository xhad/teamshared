---
type: research
title: "Screenpipe — ambient desktop memory research"
author: screenpipe/Mediar, Inc. (public repo + marketing site)
origin: https://screenpipe.com/
captured: 2026-06-23
note: >
  External product/architecture research from screenpipe.com, GitHub README,
  and public docs. Vendor claims on PII scrubbing, pricing, and enterprise
  deployment — not user research. Screenpipe is a *local-first ambient capture*
  product (screen + audio → searchable memory + MCP + Pipes), not a multi-tenant
  org brain. YC S26.
---

# Screenpipe — ambient desktop memory research

Captured 2026-06-23 from [screenpipe.com](https://screenpipe.com/) and
[screenpipe/screenpipe](https://github.com/screenpipe/screenpipe) (19k+ GitHub
stars, source-available Screenpipe Commercial License). Y Combinator S26.
Founded 2024, San Francisco (Mediar, Inc.; founder Louis Beaumont).

Screenpipe's category: **24/7 local desktop memory** — continuous screen and
audio capture, on-device storage, natural-language search, MCP for coding
assistants, and scheduled "Pipes" agents triggered by work activity. Not
durable team knowledge infrastructure — it records *what happened on your
machine*.

## Positioning

> "AI that knows what you've seen"

> "you forget what you did last tuesday - screenpipe doesn't"

> "it records your screen and calls on-device, so you (and your AI) can recall
> anything, summarize meetings, and automate the busywork. private, local, yours"

> "24/7 memory for your desktop"

Compared to TeamShared: Screenpipe does not pitch multi-tenant org scoping,
five memory pillars, distillation workers, or a human console wiki — it pitches
**ambient capture of screen + audio** with local SQLite storage and agent
automation on top.

## Core loop

```
screen + audio → local storage (SQLite + JPEG frames) → AI search / MCP / Pipes
```

From README:

> "screenpipe turns your computer into a personal AI that knows everything
> you've done. record. search. automate. all local, all private, all yours"

## Capture architecture

### Event-driven screen capture

> "Instead of recording every second, screenpipe listens for meaningful events
> — app switches, clicks, typing pauses, scrolling — and captures a screenshot
> only when something actually changes."

Each capture pairs screenshot + OS accessibility tree (buttons, labels, text
fields). OCR fallback when accessibility unavailable (Apple Vision / Windows
OCR / Tesseract). Idle fallback captures periodically.

Specs (README + site):

| Resource | Claim |
|---|---|
| CPU | 5–10% typical |
| RAM | 0.5–3 GB |
| Storage | ~5–10 GB/month (~20 GB/month on marketing site) |
| Monitors | All connected monitors |

### Audio transcription

System audio + microphone. Local Whisper (Large-V3-Turbo) or cloud Deepgram.
Speaker diarization. Works with Zoom, Meet, Teams, etc.

macOS 14.4+: per-app audio exclusion via `~/.screenpipe/audio-exclusions.json`.

### Storage & search

- Local SQLite with FTS5 full-text search
- Screenshots as JPEG on disk (~300 MB/8hr vs ~2 GB continuous recording claim)
- REST API on localhost:3030 — search, frames, audio, raw SQL
- Natural language search across accessibility text, OCR, audio transcripts
- Filter by app, window title, browser URL, date range

## Privacy & security (headline differentiator)

Marketing site emphasizes three proof points:

1. **Open source** — "Read the code that records you." (Rust core, 19k+ stars)
2. **Local-first** — "Your memory is a folder on your disk."
3. **Open APIs** — "Query it like a database. It is one."

### Exclusion at source

> "Exclude any app, window, or URL — those are dropped at the source."

Examples on site: 1Password app, personal finance URLs, specific windows.

### On-device PII scrubbing

> "Everything else is scrubbed by a Screenpipe model on your machine that removes
> cards, SSNs, and keys before anything is saved."

> "We built our own AI model from scratch, just to catch private info — and it
> catches more than OpenAI's, Google's, or Microsoft's filters do."

Alpha PII model (screenleak) released 2026-05-29 — claimed 9ms on consumer
device, outperforming Google/Microsoft/OpenAI on computer recording data.

Runs on Apple Neural Engine / Windows GPU — "instant, and free forever."

### Encryption & sync

- Optional encryption at rest
- Optional end-to-end encrypted sync between devices (Pro tier)
- No account required for core app

## Pipes — scheduled AI agents on captured data

> "Agents that act on your work, not just remember it."

Pipes are markdown-defined agents (`pipe.md`) with triggers and schedules.
Examples from site and README:

| Pipe | Trigger / purpose |
|---|---|
| meeting-notes | `meeting_ended` → summary + action items → notes |
| day-recap | Today's accomplishments, key moments, unfinished work |
| standup-update | What you did, what's next, blockers |
| time-breakdown | Time by app, project, category |
| ai-prompt-journal | Capture prompts sent to AI tools → Obsidian/markdown |
| Digital clone / CRM update / Deal spotter | Marketing site demos |

> "Triggers on-device. Writes to Notion, HubSpot, Obsidian, Sheets, and your
> calendar."

Pipe YAML frontmatter supports deterministic data permissions:

- `allow-apps`, `deny-apps`, `deny-windows` (glob patterns)
- Content types: `ocr`, `audio`, `input`, `accessibility`
- `time-range`, `days` (e.g. work hours only)
- `allow-raw-sql: false`, `allow-frames: false`

Enforcement at three layers (README): skill gating, agent interception, server
middleware with per-pipe cryptographic tokens — "Not prompt-based. Deterministic."

## MCP integration (direct overlap with TeamShared)

> "screenpipe runs as an MCP server, allowing AI assistants to query your screen
> history"

Install:

```bash
claude mcp add screenpipe -- npx -y screenpipe-mcp@latest
```

Works with Claude Desktop, **Cursor**, VS Code (Cline, Continue), any MCP client.

Example prompts (README): "what did i see in the last 5 mins?", "summarize today
conversations", "create a pipe that updates linear every time i work on task X"

**Zero configuration** via npx — contrasts with TeamShared's bearer-token +
`install.sh` onboarding.

## App connections (48 listed on site)

Slack, Gmail, Notion, Linear, Google Calendar, GitHub, Google Docs/Sheets,
Meet, Zoom, Teams, Discord, HubSpot, Salesforce, Obsidian, Ollama, OpenAI,
Claude, Datadog, Sentry, Vercel, Zapier, n8n, etc.

> "Connect once. Pipes use them automatically."

TeamShared's connector story (Slack, GitHub, Notion in prod-plan) is aspirational;
Screenpipe ships a broad integration *surface* for Pipes output, not necessarily
deep ingest connectors.

## Teams & enterprise

[screenpi.pe/team](https://screenpi.pe/team) — fleet deployment:

- Central config management (capture settings, app filters, URL rules)
- Shared pipes deployed team-wide
- Per-pipe AI data permissions (YAML, OS-level enforcement)
- **Privacy boundary**: admins control capture + AI access; **employee data never
  leaves device**
- Employee override: can add stricter filters, cannot weaken admin rules
- MDM: Intune, SCCM, Robopack
- Enterprise: SSO/SAML, audit logs, SLA, SOC 2 / HIPAA ready

Marketing demo: "screenpipe · admin · fleet — policy applied" across macOS,
Windows, Linux endpoints — all recording locally.

This is **fleet-managed local capture**, not a shared cloud brain. Each device
holds its own SQLite corpus; there is no org-wide semantic search API in the
marketing copy.

## Pricing (2026)

| Tier | Price | Notes |
|---|---|---|
| Standard | $25/mo | Local capture, search, timeline |
| Pro | $50/seat/mo | + cloud sync, cloud AI, integrations; 5+ seats self-serve |
| Enterprise | $150/seat/mo | MDM, SSO/SAML, admin dashboard, shared pipes, per-pipe permissions |
| Source build | Free (personal non-commercial) | Commercial use requires license |
| Lifetime | Legacy only | No longer sold |

Existing lifetime licenses remain valid.

## Competitive landscape (per Screenpipe)

Positioned against Rewind/Limitless, Microsoft Recall, Granola, Otter.ai:

| Feature | screenpipe | Rewind/Limitless | Microsoft Recall | Granola |
|---|---|---|---|---|
| Source-available | ✅ | ❌ | ❌ | ❌ |
| Platforms | macOS, Win, Linux | macOS, Win | Windows only | macOS only |
| Data storage | 100% local | Cloud required | Local | Cloud |
| Multi-monitor | ✅ | Active window only | ✅ | Meetings only |
| Audio | ✅ Local Whisper | ✅ | ❌ | ✅ Cloud |
| Developer API | ✅ REST + SDK | Limited | ❌ | ❌ |
| Plugin system | ✅ Pipes | ❌ | ❌ | ❌ |
| Team deployment | ✅ Central config | ❌ | ❌ | ❌ |

## Technical stack

- Rust core (Tauri desktop app + capture engine)
- TypeScript UI
- SQLite + FTS5 + JPEG frame store
- Localhost REST API (port 3030)
- SDKs: Tauri, Electron, Swift; JS/TS `@screenpipe/js`
- CLI: `npx screenpipe record`

## License change (2026-06-10)

> "we updated our license to keep screenpipe sustainable — more funding, more
> shipping, better product"

Moved from fully open MIT-style to **Screenpipe Commercial License**
(source-available; personal non-commercial OK; commercial use requires license).
Desktop app remains subscription-gated for signed builds.

## Overlap vs TeamShared

| Dimension | Screenpipe | TeamShared |
|---|---|---|
| **Primary artifact** | Screen frames + audio transcripts | Agent turns, semantic/episodic facts, skills, work |
| **Scope** | Single device (optional encrypted sync) | Multi-tenant org, cross-agent shared brain |
| **Capture model** | Ambient 24/7 OS-level | Agent-initiated MCP writes + optional server-side turn capture |
| **Query surface** | MCP + REST search over local SQLite | MCP recall/think + console wiki |
| **Human UX** | Timeline DVR, desktop app | `/app` console, wiki, work queue |
| **Automation** | Pipes (triggered agents on capture) | Distiller, curator, workflows |
| **Privacy story** | Local-first, exclude-at-source, PII model | Org RLS, bearer tokens, OTP console |
| **Enterprise** | MDM fleet + per-pipe permissions; data on device | Multi-tenant SaaS, SSO roadmap, audit |
| **Distribution** | 19k★, YC S26, $25–150/seat | teamshared.com, Cursor plugin, smaller footprint |
| **Coding agent hook** | MCP queries screen history | MCP memory_recall + session logging |

## What Screenpipe does NOT claim

- Multi-tenant org memory shared across agents on different machines (without sync)
- Semantic distillation into durable facts with subject/tags/kinds
- Work queue, strategic OKRs, approval queues
- Graph relationships between entities (beyond search)
- Gap analysis on recall ("what the brain doesn't know")
- Server-side capture middleware independent of client hooks

## YC / category signal

Screenpipe joined **YC S26** (2026-05-14 announcement in README). Same YC batch
era as the "company brain" RFS momentum — but Screenpipe targets **personal
ambient memory** and **desktop automation**, not "every company's shared agent
context."

Site social proof: "used by engineers and researchers at" Microsoft, Google,
NVIDIA, Intel, Shopify, Atlassian, Datadog, Adobe, MIT, Stanford, etc.
(logo wall — unverified depth of deployment).
