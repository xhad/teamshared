# metrics-tree — TeamShared

**Input goal:** *Teams adopt TeamShared as their shared agent memory layer* (the
product outcome implied by `prod-plan.md`; the doc itself only states the
engineering goal "production ready for multi-tenant org customers").

**Competing definitions the PM should resolve:**

| Definition | Top metric would be… |
|---|---|
| **A — Product value** (recommended primary) | Orgs where agents reliably recall useful shared memory |
| **B — Revenue** | Paying orgs with sustained usage |
| **C — Delivery** | Production-readiness checklist completion |

This tree assumes **Definition A**. If the team is optimizing for B or C, the
decomposition changes materially.

---

## Top metric

**Weekly Orgs with Successful Shared Recall (WOSR)**

```
WOSR = count of distinct org_id
       where, in the trailing 7 days:
         ≥ 2 distinct agent_id made ≥ 1 memory_recall call
         AND ≥ 1 of those calls returned ≥ 1 record
         AND ≥ 1 returned record was written by a *different* agent_id
```

This is the measurable version of "shared agent brain": recall happened, it
wasn't empty, and it crossed agent boundaries. A single-agent org recalling its
own writes is necessary but not sufficient for the product thesis.

---

## Input metrics

WOSR decomposes multiplicatively into orgs that pass each gate:

```
WOSR = Orgs onboarded
     × Orgs with ≥2 active agents        (agent breadth)
     × Orgs with recall attempted        (recall adoption)
     × Orgs with non-empty recall        (recall quality — retrieval works)
     × Orgs with cross-agent recall hit  (shared brain — the thesis)
```

| Input | Operator | Instrumentable as |
|---|---|---|
| **Orgs onboarded** | filter | `org_id` with ≥1 `tsk_*` key minted and used |
| **Orgs with ≥2 active agents** | × | distinct `agent_id` (bearer attribution) with ≥1 MCP call / 7d |
| **Orgs with recall attempted** | × | distinct org with ≥1 `memory_recall` / 7d |
| **Orgs with non-empty recall** | × | recall where `records.length ≥ 1` |
| **Orgs with cross-agent recall hit** | × | recall where `record.agent ≠ caller agent` |

Secondary input (feeds recall quality, not in the WOSR equation directly):

| Input | Role |
|---|---|
| **Distilled memories per org / week** | Supply side — is the brain filling? |
| **Recall latency p95** | Quality guardrail — slow recall → abandoned |
| **Consent-approved capture batches / org / week** | Capture funnel — no capture → nothing to recall |

---

## Leading indicators

Observable sooner than WOSR (days, not weeks):

| Input metric | Leading indicator(s) |
|---|---|
| Orgs onboarded | Console sign-in completed; first `tsk_*` key minted; plugin install curl exit 0 |
| ≥2 active agents | Second distinct bearer token used within same `org_id` |
| Recall attempted | `memory_session_open` followed by `memory_recall` in same session |
| Non-empty recall | `memory_remember` writes in prior 7d for same org (supply exists) |
| Cross-agent recall hit | `memory_recall` with no `agent=` filter (shared-brain default) returning records from ≥2 distinct writers |
| Distilled memories | Distill queue depth → 0; episodic/semantic count delta per org |
| Recall latency | MCP tool round-trip time; Postgres/pgvector query span in traces |
| Capture batches | Consent grant active + `POST /sessions/turns` accepted |

---

## Instrumentation gaps

Each item is a metric in the tree TeamShared likely **cannot measure today**
without new tracking. Label: **you must measure this.**

| Metric | Gap |
|---|---|
| **Cross-agent recall hit** | `memory_recall` returns records with `agent` attribution, but there is no event tying "caller agent" vs "writer agent" into a product analytics stream |
| **Non-empty recall rate per org** | MCP tool success is logged; org-scoped recall hit/miss rates are not aggregated |
| **Active agents per org** | Bearer tokens map to agents, but no weekly-active-agent rollup |
| **Recall latency p95 per org** | OpenTelemetry spans may exist; no SLO dashboard on recall path |
| **Distilled memories per org / week** | Mem0/SQL stats exist (`GET /memory`, console home); not time-series per org |
| **Consent-approved capture batches** | `consent_denied_capture` metric exists; accepted-batch funnel per org is not surfaced |
| **Session → recall correlation** | Working memory sessions exist; no join from `session_id` to subsequent recall calls |
| **Paying orgs** (if optimizing for Definition B) | No billing instrumented — entire revenue branch is uninstrumentable today |

Until cross-agent recall hit and non-empty recall rate are measured, WOSR is
structurally defined but **not actionable**.

---

## Move this first

**Non-empty recall rate per org** — the fraction of `memory_recall` calls that
return ≥1 record, broken down by org.

Reasoning: WOSR's last two gates (non-empty, cross-agent) both require recall to
work at all. The assumption audit flagged "LLM distillation yields trustworthy
memory" as High-risk; an empty or irrelevant recall is the earliest signal that
the supply chain (capture → distill → store → retrieve) is broken. Instrumenting
this is cheap relative to building Phase 3 enterprise features, and it gates
every downstream metric — agents won't adopt, second agents won't onboard, and
orgs won't pay for a brain that returns nothing.

**Goodhart risk:** Optimizing non-empty recall rate alone incentivizes stuffing
low-quality memories to avoid empty results. Pair the metric with a manual
quality sample (PM reads 10 random recall results per org per week) until a
recall-usefulness score exists. Do not target a numeric benchmark until baseline
is measured.

---

*Structural tree only — no targets or industry benchmarks. The PM supplies the
numbers once instrumentation exists.*
