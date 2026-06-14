# Assumption audit — TeamShared

## Health context

Corpus health is **thin**: 5 sources, all internal product intent, effectively
one source-type ("what the team intends"). On a thin corpus **single-source is
the default, not an anomaly** — almost every claim in the graph rests on one
document, because the documents are all by the same authors. So the bar for
"this needs validating" resets: the triage below ranks by *the decision at risk*,
not by evidence-thinness (everything is thin). Totals: **8 assumptions** (zero
provenance) and **~30 single-source claims** (one source each).

## Assumptions (zero provenance)

Ranked by the decision that breaks if the assumption is wrong.

### High

1. **Teams actually want cross-agent shared memory.**
   - Decision at risk: the entire roadmap. Every phase (multi-tenancy, scopes,
     connectors, enterprise) assumes the shared-brain thesis is wanted.
   - Source of the assumption: voiced internally — `prod-plan.md` calls it "a
     proof of concept for shared agent memory" and plans straight to production
     with no demand evidence in between.

2. **Orgs will pay for 'shared agent context' as infrastructure.**
   - Decision at risk: whether there's a business at all; pricing and GTM.
   - Source: assumed in the goal "production ready for multi-tenant organization
     customers" — customers are named, never quoted.

3. **Default cross-agent visibility (the "shared brain") is what users want.**
   - Decision at risk: the core read-path default (AGENTS.md pins "read paths are
     agent-unscoped by default"). If buyers expect isolation-by-default, the
     headline feature is a trust/security liability.
   - Source: asserted as "Shared memories across teams and agents" with no user
     on record preferring shared-by-default over private-by-default.

4. **LLM distillation yields durable, low-noise memory worth recalling.**
   - Decision at risk: recall quality — the product's entire value. If distilled
     memory is noisy or wrong, every other feature sits on bad data.
   - Source: assumed in "Distill prompt extracts only durable knowledge" with no
     quality measurement.

### Medium

5. **Consent-first capture friction is what gates adoption.**
   - Decision at risk: scope of a whole implementation phase. Declared a "hard
     constraint" / locked decision, yet no user or buyer is quoted demanding it.
   - Source: `memory-wiki-plan.md` "Consent-first, client-sanitized, push-only".

6. **SSO/SAML/SOC2 gate the deals worth chasing.**
   - Decision at risk: Phase 3 enterprise sequencing. May be built too early (or
     too late) without a design partner who gates on it.
   - Source: `prod-plan.md` "Enterprise security baseline".

7. **Humans will actually browse the memory wiki/console.**
   - Decision at risk: the console + curator + wiki build (a full phase) — large
     investment with no audience if humans never open `/app`.
   - Source: `memory-wiki-plan.md` "browse the data as a human-readable,
     continuously updating wiki".

### Low

8. **Slack/GitHub/Notion/etc. connectors are the adoption lever.**
   - Decision at risk: connector roadmap ordering — recoverable; connectors can
     be reprioritized once real usage exists. Listed as "low" only because it's
     downstream of #1–#2 being true at all.
   - Source: `plan.md` connector list.

## Single-source claims (one source)

On a thin corpus these are the rule, so this lists only the **load-bearing**
ones — claims a major decision leans on that rest on a single document.

### High

- **"Context rot" is the pain TeamShared solves.** Source: `plan.md` (a general
  industry-landscape paragraph, *not* a TeamShared user). Triangulate with: one
  real interview where a team describes losing agent context across sessions.
- **No cross-tenant leakage "by design".** Source: `plan.md` principle. This
  blocks the production outcome and is a one-way-door security claim. Triangulate
  with: a security review / pen-test result, not just a stated principle.

### Medium

- **The competitive landscape** (Pinecone, Neo4j, LangChain/LlamaIndex,
  Cloudflare Agent Memory, Hindsight). All five come from a *single paragraph* in
  `plan.md`. Triangulate with: an actual competitive teardown — what a buyer
  evaluates TeamShared against and why they'd switch.
- **"Just-in-time retrieval" and "four pillars" insights.** Source: `plan.md`
  landscape notes. Useful framing; not evidence of user demand. Triangulate with:
  a user describing the recall behavior they actually want.

## Triage recommendation

Validate the **Highs in order**: thesis (#1) and willingness-to-pay (#2) first —
they gate everything, and a handful of discovery interviews with target teams can
move both in a week. Then the **shared-brain default (#3)**, because it's a
one-way-door product/security decision that's cheap to ask about now and
expensive to reverse later. Defer #4 (distillation quality) to a measurement once
there's real captured data. Everything in Medium/Low is downstream — don't spend
validation cycles on connector ordering or SSO sequencing until #1 and #2 hold.

The team will plan against whatever it does not question. These are the things to question first.
