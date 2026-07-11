# TeamShared design-partner runbook

Use this runbook for a five-interview, 3–5-partner validation cycle. The goal is
to observe repeatable cross-agent value, not to demo every feature.

## Target participant

- Engineering team of roughly 5–20 people.
- Uses at least two agent sessions, users, or harnesses.
- Can name a recent decision or piece of context that another agent failed to know.
- Will use TeamShared on real work for four weeks and permit privacy-safe usage metrics.

Exclude individual-memory-only use cases and teams seeking a generic vector database.

## Problem interview (30 minutes)

Do not show the product until after the current workflow is understood.

1. Tell me about the last time one agent lacked context another teammate or agent had.
2. What work was repeated, delayed, or done incorrectly?
3. How often does this happen? What do you do today?
4. Which information should automatically be shared? Which must remain private?
5. How would you detect and correct a false or stale memory?
6. Who would approve installing an organization-wide memory service?
7. What would make you remove it after a week?
8. What does the current workaround cost in time or money?
9. If this reliably prevented the failure, what would you expect to pay?

Capture exact quotes and concrete incidents. Do not count feature enthusiasm as demand.

## Concierge onboarding

Before the call, add participants to the intended shared org; do not leave them in
an empty personal org.

1. Sign in to `/app`, switch to the shared org, and mint one key per agent label.
2. Run `curl -fsSL https://teamshared.com/install.sh | bash`.
3. Restart each harness and call `health`.
4. Run `teamshared doctor --url https://teamshared.com --token …`.
5. Agent A records a real team decision with source/provenance.
6. Agent B starts without being told the decision and recalls it.
7. Verify the result is correct, sourced, and useful to the task.
8. Record elapsed minutes and every founder/operator intervention.

Success is a real cross-agent task outcome, not a successful API call.

## Weekly usefulness review

Sample 10 recall attempts per partner. Never copy secrets or full private prompts
into the review artifact.

For each sample record:

- task category and anonymized query anchor;
- returned / empty;
- cross-agent / same-agent;
- useful: yes / partial / no;
- correctness: correct / stale / false / unverifiable;
- provenance adequate: yes / no;
- failure stage: capture / distill / store / retrieve / scope / guidance;
- action and owner.

Run private fixtures with:

```bash
cp eval/partner_queries.example.json eval/private/acme-week-1.json
python scripts/eval_partner_replay.py eval/private/acme-week-1.json \
  --url https://teamshared.com/mcp --token 'tsk_…'
```

## Pricing interview

Ask only after the participant has used the product:

1. What changed in your workflow?
2. What would you do if TeamShared disappeared tomorrow?
3. Who owns the budget for this problem?
4. Would you continue at $25, $100, or $250 per team per month? Why?
5. What evidence or control is required before purchasing?
6. Will you sign a paid pilot or letter of intent now?

Count a paid pilot, procurement step, or explicit budget-backed commitment as
purchase intent. Do not count “sounds reasonable.”

## Week 8 and week 12 scorecard

Continue only when all are true:

- at least 3 partner orgs repeat successful cross-agent recall in 3 of 4 weeks;
- the majority of reviewed recalls are useful, correct, and adequately sourced;
- median onboarding-to-first-cross-agent-recall is under 20 minutes;
- no critical tenant, auth, or memory-safety incident occurred;
- at least 2 partners show budget-backed willingness to pay.

Pivot the sharing model if durable memory is valued but shared-by-default is
rejected. Stop broad platform work if use remains single-agent, demo-driven, or
dependent on founder prompting.
