# TeamShared production checklist

Use the Makefile so `.env` and host port overrides are always applied.

## First deploy

1. Copy `.env.example` to `.env`.
2. Set provider credentials, `TEAMSHARED_SESSION_SECRET`,
   `TEAMSHARED_JOB_SIGNING_SECRET`, SMTP, and production database credentials.
3. Run `make migrate`.
4. Run `make provision-app-role`.
5. Run `make verify-rls`; do not serve partner traffic unless it passes.
6. Run `make build`.
7. Confirm `make health` reports server, Redis, Postgres, semantic store,
   distiller, curator, and queues healthy. Graph may be `disabled`.
8. Run `teamshared doctor --url <public-url>`.
9. Mint a temporary key and run `teamshared doctor --url <public-url> --token
   <key> --write-smoke`, then revoke the key.

## Partner readiness

- SMTP delivery works and the default OTP lifetime is five minutes.
- The participant belongs to the intended shared org before installing.
- One key exists per agent/harness label.
- Console home shows key usage, two active agents, and cross-agent recall.
- Retention settings and export/erasure procedures match the partner agreement.
- No raw prompts or query content are exported into product analytics.

## Daily checks

- `/health`: dependencies, worker heartbeats, queue alerts.
- `/metrics`: recall attempts/results/latency and queue depths.
- `/app`: seven-day shared recall activation and recent audit events.
- Dead-letter queues: investigate any non-zero depth.
- Preview retention with `teamshared retention-enforce --org-id <uuid>`; schedule
  `teamshared retention-enforce --org-id <uuid> --apply` daily after reviewing
  the first dry-run output.

## Weekly validation

- Review 10 recall attempts per partner using
  `product/knowledge/design-partner-runbook.md`.
- Replay private expected-result fixtures with
  `scripts/eval_partner_replay.py`.
- Record onboarding time, cross-agent repeat usage, usefulness, correctness,
  provenance, and concrete purchase intent.

## Recovery

Follow `infra/runbooks/backup_restore_dr.md` and
`infra/runbooks/queue_observability.md`. Run a restore drill before promising an
RPO/RTO to a design partner.
