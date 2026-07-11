# Clean-room activation run — 2026-07-11

## Result

- Production image build: passed.
- Migrations: passed.
- App-role provisioning and RLS verification: passed.
- Real Postgres/Redis integration suite: 23 passed.
- Two agent identities: agent A wrote a marked decision; agent B recalled it.
- Cross-agent audit metric: passed.
- Console sign-in, key mint, and onboarding UI: covered by console tests.
- Approximate cold elapsed time including image pulls: 10–11 minutes.

This establishes an engineering baseline below the 20-minute target. It does not
replace timing a real participant from sign-in through use in their harness.

## Manual interventions observed

1. The checkout had no `.env`; the run used `.env.example` plus documented host
   ports 5433/6380.
2. The first integration invocation omitted the app-role variables and therefore
   connected as the Postgres superuser. Rerunning with
   `TEAMSHARED_PG_APP_USER`/`TEAMSHARED_PG_APP_PASSWORD` correctly exercised RLS.
3. The smoke exposed that newly minted agent keys were not bound to the `agent`
   role. API and console mint paths now create the idempotent role binding.
4. The smoke exposed that retrieval audit writes omitted explicit `org_id`
   outside a context variable. Retrieval now supplies the request org directly.

## Reproduction

Use a real `.env` and the canonical Make targets:

```bash
make migrate
make provision-app-role
make verify-rls
make check
pytest -m integration
```

Then run `teamshared doctor --url <public-url> --token <key> --write-smoke` and
time a participant through the concierge proof in
`product/knowledge/design-partner-runbook.md`.
