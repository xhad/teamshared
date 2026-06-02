You are a senior staff engineer and product-minded systems architect. Help me plan and implement the production-readiness roadmap for **TeamShared**, an agent memory and shared-context system for teams and organizations.

## Context

TeamShared is currently a proof of concept for shared agent memory. The goal is to make it production ready for multi-tenant organization customers.

The system should allow teams, companies, and agentic workflows to share structured and unstructured memory across users, agents, projects, and tools. It should support secure retrieval, scoped memory access, org/team/project boundaries, auditability, permissioning, and reliable production operations.

Think of TeamShared as infrastructure for “shared agent context” across an organization.

## Main Objective

Create a detailed technical plan to evolve TeamShared from PoC to production for multi-tenant org customers.

The output should be specific, implementation-oriented, and suitable for engineering execution.

## Key Questions to Answer

1. What does “production ready” mean for TeamShared?

2. What architecture should we use for multi-tenant org support?

3. How should tenants, organizations, users, teams, projects, agents, memories, and permissions be modeled?

4. How should we isolate tenant data safely?

5. How should memory ingestion, retrieval, ranking, updating, expiration, and deletion work?

6. How should we handle authentication, authorization, audit logs, and admin controls?

7. How should we support integrations such as Slack, GitHub, Linear, Notion, Google Drive, MCP servers, and internal tools?

8. How should we make the system reliable, observable, scalable, and secure?

9. What should the production roadmap look like across MVP, beta, and enterprise-ready phases?

10. What are the highest-risk areas and how should we mitigate them?

## Product Requirements

TeamShared should support:

- Multi-tenant organizations

- Org-level, team-level, project-level, user-level, and agent-level memory scopes

- Shared memories across teams and agents

- Private memories for individuals or agents

- Admin-configurable retention policies

- Explicit memory creation, automatic memory extraction, and human approval flows

- Search and retrieval over both structured metadata and vector embeddings

- Role-based access control

- Fine-grained permission checks before retrieval

- Audit logs for memory creation, reads, updates, deletes, and permission changes

- Data deletion and export

- Integrations with external tools

- API access for agents and applications

- Web dashboard for admins and users

- Observability, metrics, tracing, and alerts

- Enterprise security baseline

## Technical Requirements

Design the system around these concerns:

### Multi-Tenancy

Define a robust tenant model.

Include:

- Organization model

- Workspace/team/project model

- User model

- Agent/service-account model

- Membership model

- Roles and permissions

- Tenant isolation strategy

- Database-level safeguards

- Vector index partitioning strategy

- Per-tenant encryption considerations

- Tenant-aware API design

Compare at least three tenant-isolation options:

1. Shared database, shared schema with `org_id`

2. Shared database, separate schema per tenant

3. Separate database/index per tenant

Recommend the best default for an early-stage production SaaS and explain when to graduate to stronger isolation.

### Memory Model

Design the core memory schema.

Include entities such as:

- `organizations`

- `users`

- `teams`

- `projects`

- `agents`

- `memberships`

- `roles`

- `permissions`

- `memory_items`

- `memory_chunks`

- `memory_embeddings`

- `memory_sources`

- `memory_events`

- `audit_logs`

- `retention_policies`

- `connectors`

- `api_keys`

- `service_accounts`

Each memory item should support:

- Content

- Summary

- Source

- Scope

- Visibility

- Owner

- Creator

- Confidence

- Importance

- Recency

- Tags

- Metadata

- Embedding references

- Version history

- Soft deletion

- Retention policy

- Access control policy

- Audit trail

### Memory Scopes

Define how memory can be scoped.

Possible scopes:

- Global/system

- Organization

- Team

- Project

- User

- Agent

- Conversation

- External source

- Temporary/session

- Private

- Shared

Explain how retrieval should respect these scopes.

For example:

An agent acting inside Project A for Org X should only retrieve memories that are visible to:

- Org X

- Project A

- The requesting user

- The requesting agent

- Any explicitly shared team or workspace scope

### Authorization

Design authorization carefully.

Include:

- RBAC model

- Optional ABAC model for advanced enterprise needs

- Permission checks on every read/write/delete

- Role hierarchy

- Admin roles

- Agent/service-account permissions

- API key scopes

- Connector permissions

- Cross-team sharing rules

- Memory visibility rules

- Prevention of cross-tenant data leakage

Example roles:

- Org Owner

- Org Admin

- Team Admin

- Project Admin

- Member

- Viewer

- Agent

- Service Account

- External Collaborator

Example permissions:

- `memory:create`

- `memory:read`

- `memory:update`

- `memory:delete`

- `memory:approve`

- `memory:share`

- `memory:export`

- `memory:admin`

- `connector:manage`

- `audit:read`

- `billing:manage`

### Retrieval System

Design the memory retrieval pipeline.

Include:

1. Request context construction

2. Tenant resolution

3. Auth/authz check

4. Scope filtering

5. Metadata filtering

6. Vector search

7. Keyword/hybrid search

8. Reranking

9. Recency/importance weighting

10. Permission recheck

11. Context packaging

12. Citation/source inclusion

13. Logging and audit event

The system must never retrieve memory before applying tenant and scope constraints.

Explain how to prevent accidental retrieval of memory from another org, team, project, user, or agent.

### Ingestion System

Design the memory ingestion pipeline.

Include:

- Explicit user-created memories

- Agent-created memories

- Automated extraction from conversations/documents

- Connector-based ingestion

- Human approval queue

- Deduplication

- Classification

- Sensitive-data detection

- PII handling

- Embedding generation

- Chunking strategy

- Metadata enrichment

- Source linking

- Versioning

- Event log

Include policies for deciding:

- What gets saved

- What should not be saved

- What requires approval

- What expires automatically

- What should be private by default

- What can be shared with a team/org

### Connectors and Integrations

Plan for connectors such as:

- Slack

- GitHub

- Linear

- Notion

- Google Drive

- Gmail

- Google Calendar

- Jira

- Confluence

- MCP servers

- Internal APIs

For each connector type, define:

- Auth model

- Sync model

- Permission mirroring

- Source metadata

- Incremental updates

- Deletion propagation

- Rate limits

- Failure handling

- Audit logs

### APIs

Design a production API surface.

Include endpoints for:

- Organizations

- Teams

- Projects

- Users

- Agents

- Memberships

- Roles

- Memories

- Memory search

- Memory retrieval

- Memory approval

- Memory deletion

- Connectors

- API keys

- Audit logs

- Admin settings

- Retention policies

Also include:

- REST API design

- Optional GraphQL considerations

- Webhook support

- MCP-compatible interface

- SDK considerations

- Idempotency keys

- Pagination

- Rate limiting

- Error model

### Security

Create a security plan.

Include:

- Authentication

- SSO/SAML/OIDC readiness

- MFA support

- API key management

- Service accounts

- Least privilege access

- Tenant isolation

- Encryption in transit

- Encryption at rest

- Optional per-tenant encryption keys

- Secret management

- Audit logging

- Admin impersonation controls

- PII detection

- Data retention

- Data deletion

- GDPR/CCPA-style export/delete readiness

- SOC 2 readiness

- Security headers

- Abuse prevention

- Prompt injection defenses for memory ingestion and retrieval

- Connector token storage

- Incident response basics

### Prompt Injection and Memory Poisoning

This is especially important.

Design defenses for:

- Malicious content entering memory

- Prompt injection from documents, Slack, GitHub issues, or webpages

- Agents retrieving unsafe instructions from memory

- Cross-user memory poisoning

- Incorrect memories being treated as facts

- Stale memory affecting decisions

- Conflicting memories

- Source trust scoring

- Human approval for high-impact memories

- Memory quarantine

- Memory confidence scoring

Include a clear policy:

Memory is context, not authority. Retrieved memory should be source-attributed, permission-checked, and optionally confidence-scored.

### Data Architecture

Recommend a practical production stack.

Assume a modern SaaS architecture.

Possible stack:

- Postgres for relational data

- pgvector or dedicated vector DB for embeddings

- Redis for cache and queues

- S3-compatible object storage for raw documents

- Background workers for ingestion and embedding jobs

- OpenTelemetry for tracing

- Structured logs

- Metrics and alerts

- Optional search engine such as OpenSearch/Meilisearch for keyword search

Compare:

- Postgres + pgvector

- Pinecone

- Weaviate

- Qdrant

- OpenSearch hybrid search

Recommend the best starting point and explain migration paths.

### Observability

Design observability for production.

Include:

- Logs

- Metrics

- Traces

- Audit events

- Ingestion job monitoring

- Retrieval latency

- Embedding cost tracking

- Search quality metrics

- Permission-denied events

- Cross-tenant access violation alerts

- Connector sync failures

- Queue depth

- API error rates

- SLOs and SLAs

Suggest dashboards and alerts.

### Reliability and Scalability

Plan for:

- Background job retries

- Dead-letter queues

- Idempotent ingestion

- Rate limiting

- Backpressure

- Horizontal scaling

- Tenant-level quotas

- Connector sync scheduling

- Database migrations

- Backup and restore

- Disaster recovery

- Zero-downtime deploys

- Feature flags

- Rollbacks

- Load testing

### Admin and User Experience

Define the minimum dashboard experience.

Include:

For org admins:

- Invite users

- Create teams/projects

- Manage roles

- Manage agents

- Manage connectors

- View audit logs

- Configure retention policies

- Export/delete data

- Review memory approval queue

- View usage and billing

For users:

- View memories they can access

- Search memory

- Edit/delete their memories

- Approve/reject suggested memories

- Manage private/shared visibility

- See where a memory came from

For developers/agents:

- API key management

- Service account management

- SDK docs

- MCP configuration

- Retrieval debugging

- Test queries

### Production Roadmap

Create a phased roadmap.

Use these phases:

#### Phase 1: Production Foundation

Goal: safe multi-tenant MVP.

Include:

- Tenant model

- Auth

- Basic RBAC

- Memory CRUD

- Scoped retrieval

- Audit logs

- Postgres schema

- pgvector search

- Basic API

- Admin dashboard

- Hard tenant isolation checks

- Basic observability

#### Phase 2: Team/Project Memory

Goal: useful org memory product.

Include:

- Teams/projects

- Agent identities

- Approval queue

- Connector framework

- Slack/GitHub/Notion initial connectors

- Hybrid search

- Reranking

- Versioning

- Retention policies

- User-facing memory controls

#### Phase 3: Enterprise Readiness

Goal: sell to serious org customers.

Include:

- SSO/SAML/OIDC

- SCIM provisioning

- Advanced audit logs

- Per-tenant encryption keys

- Data residency option

- Advanced RBAC/ABAC

- Compliance exports

- Connector permission mirroring

- Security reviews

- SOC 2 preparation

- SLAs

- Admin analytics

#### Phase 4: Advanced Agent Memory Network

Goal: differentiated agentic memory infrastructure.

Include:

- MCP-native interface

- Agent-to-agent shared memory

- Memory trust graph

- Conflict resolution

- Memory provenance

- Confidence scoring

- Memory decay

- Organization knowledge graph

- Workflow-aware retrieval

- Automated context packs

- Cross-tool agent collaboration

### Deliverables

Please produce the following:

1. Executive summary

2. Production-readiness checklist

3. Recommended architecture

4. Multi-tenant data model

5. Memory lifecycle design

6. Authorization model

7. Retrieval pipeline

8. Ingestion pipeline

9. API design

10. Security model

11. Observability plan

12. Reliability plan

13. Connector architecture

14. Admin dashboard requirements

15. Roadmap by phase

16. Engineering task breakdown

17. Risk register

18. Open questions

19. Suggested database schema

20. Suggested folder/service architecture

## Output Format

Use clear sections with headings.

Be specific. Avoid vague advice.

Where useful, include:

- Tables

- Entity diagrams in text

- Pseudocode

- Example database schemas

- Example API routes

- Example permission checks

- Example retrieval flow

- Example ingestion flow

- Example engineering tickets

Prioritize practical implementation over theoretical discussion.

Assume I want to start building immediately.

---

## Security & production hardening roadmap (staged)

Architectural review (2026-06) distilled into five shippable stages. Each stage
keeps `main` deployable; prefer feature flags and tests that pin contracts.

### Guiding principles

| Principle | Implication |
|-----------|-------------|
| Fail closed in prod | `TEAMSHARED_DEPLOYMENT_ENV=production` rejects unsafe config at startup |
| Identity | Org-bound `tsk_*` API keys only (legacy file tokens removed) |
| Test the contract | Route registry + security metrics in CI |
| Feature flags | e.g. `dashboard_public_content`, procedure review (later) |

### Stage 0 — Baseline & guardrails

| ID | Work | Status |
|----|------|--------|
| 0.1 | Prod config validator (`config_validate.py`, `TEAMSHARED_DEPLOYMENT_ENV`) | **Done** |
| 0.2 | Route inventory test (`server/route_policy.py`) | **Done** |
| 0.3 | Security metrics (`auth_rejected`, `otp_failed`, `consent_denied_capture`, `ingestion_quarantined`) | **Done** |

**Exit:** invalid prod `.env` refuses startup; new routes fail CI without classification.

### Stage 1 — Public surface & abuse resistance (~1 week)

| ID | Work | Status |
|----|------|--------|
| 1.1 | `/memory` counts-only by default (`dashboard_public_content=false`) | **Done** |
| 1.2 | Redis rate limits (mint, OTP, MCP) | **Done** |
| 1.3 | `route_policy` drives `BearerAuthMiddleware` bypass list | **Done** |

### Stage 2 — Identity plane consolidation (2–3 weeks)

| Phase | Work | Status |
|-------|------|--------|
| 2a | Mint `tsk_*` API keys only; migration CLI; dual-read legacy | **Done** |
| 2b | `legacy_token_used` metric + deprecation window | **Done** |
| 2c | Remove legacy file tokens; `tsk_*` keys only | **Done** |

### Stage 3 — Memory path consistency (1–2 weeks)

| ID | Work |
|----|------|
| 3.1 | Per-request `Authorizer` for `MemoryService` (no stale RBAC cache) | **Done** |
| 3.2 | `memory_procedure_set` through ingestion (PII/injection/review) | **Done** |
| 3.3 | Audit `agent=` attribution overrides | **Done** |

### Stage 4 — Worker trust & scale (~2 weeks)

| ID | Work |
|----|------|
| 4.1 | HMAC-signed distill/curate jobs |
| 4.2 | Redis-backed rate limit + idempotency for multi-instance |
| 4.3 | Capture/consent + queue observability alerts |

### Stage 5 — Enterprise layer (ongoing)

Org memory policies, export/erasure, Neo4j hardening, Mem0 removal, console CSRF, threat model / pen test.

### PR slicing (review-friendly)

```
Stage 0: config validator | route_policy + test | metrics wiring
Stage 1: dashboard | redis rate limit | auth uses route_policy
Stage 2: tsk mint | migrate CLI | remove legacy
Stage 3: authorizer factory | procedure pipeline | override audit
```

### Critical path

`0 → 1.1 → 1.2 → 2a → 2c → 3.2`

### Rollout notes

| Milestone | User impact |
|-----------|-------------|
| Stage 1 | `/memory` no longer shows memory snippets by default |
| Stage 2a | Re-redeem invite → `tsk_*` token |
| Stage 2c | Legacy `teamshared_*` file tokens removed; use `tsk_*` only |
| Stage 3 | Procedures may enter approval queue |