---
type: research
title: "Palantir Foundry — ontology & ontological data structures"
author: Palantir public documentation + practitioner synthesis
origin: https://palantir.com/docs/foundry/ontology/
captured: 2026-06-19
note: >
  External architecture research from Palantir Foundry docs, developer community,
  and practitioner write-ups. Enterprise product marketing + platform design —
  not user research. Treat as directional competitive/architectural intelligence
  for TeamShared ontology design, not a build spec.
---

# Palantir Foundry ontology research

Captured 2026-06-19 from [Palantir Foundry Ontology docs](https://palantir.com/docs/foundry/ontology/core-concepts/),
[Ontology system architecture](https://palantir.com/docs/foundry/architecture-center/ontology-system/),
[Interfaces](https://palantir.com/docs/foundry/interfaces/interface-overview/),
[Object backend / OMS](https://palantir.com/docs/foundry/object-backend/overview/),
developer community threads, and practitioner analyses (Towards AI, Medium).

## Positioning (Palantir)

> The Ontology is the digital twin of an organization, a rich semantic layer that
> sits on top of the digital assets (datasets and models) integrated into Foundry.

> The Ontology is an operational layer for the organization… containing both the
> semantic elements (objects, properties, links) and kinetic elements (actions,
> functions, dynamic security) needed to enable use cases of all types.

> The Ontology is the API of your organization; a shared layer between engineers,
> business users, and AIP agents.

> In a decision-centric system, you need three things: the data, the logic, and
> the actions.

Foundry frames ontology as **decision infrastructure**, not a knowledge base or
search index. Humans and AI agents collaborate through the same semantic + kinetic
layer.

## Core ontology primitives

### Object types (nouns / schema)

> An object type is the schema definition of a real-world entity or event. An
> object refers to a single instance of an object type.

Dataset analogy (official):

| Datasets | Ontology |
| --- | --- |
| Dataset | Object type |
| Row | Object |
| Column | Property |
| Field | Property value |
| Join | Link type |

Object types represent business concepts (`Employee`, `PurchaseOrder`, `Aircraft`,
`Customer`, `MaintenanceEvent`) — not table names from source systems.

### Properties

> A property of an object type is the schema definition of a characteristic of a
> real-world entity or event.

Properties are typed (text, numeric, categorical, geospatial, media, etc.).
**Shared properties** can be reused across object types for consistent modeling
(e.g. `Location`, `CreatedAt`).

### Link types (relationships)

> A link type is the schema definition of a relationship between two object types.

Links are first-class schema, not inferred joins. Design guidance warns against
"spiderweb" ontologies — too many low-value links — and against over-linking that
makes objects unusable.

### Action types (verbs / governed writes)

> An action type is the schema definition of a set of changes or edits to objects,
> property values, and links that a user can take at once. It also includes the
> side effect behaviors that occur with action submission.

Action types are Foundry's key differentiator vs traditional data lakes:

- **Parameters** — structured input from operators or agents
- **Validation rules** — business constraints before execution
- **Side effects** — create links, notify, write back to SAP/ERP/webhooks
- **Audit trail** — every action versioned and traceable
- **Permissions** — who may apply which action on which objects

> While traditional dashboards focus on read-only insights, action types enable
> users to take action.

### Interfaces (polymorphism)

> An interface is an Ontology type that describes the shape of an object type and
> its capabilities. Interfaces allow for consistent modeling of and interaction
> with object types that share a common shape.

Example: a `Facility` interface with `Facility Name` and `Location` properties,
implemented by `Airport`, `Manufacturing Plant`, `Maintenance Hangar`.

Interfaces support:

- Shared property shapes across object types
- Link type constraints
- Actions that operate on any implementing type
- Object-set search/sort by interface (OSDK)

### Functions (logic on ontology)

> A function is a piece of code-based logic… natively integrated with the Ontology:
> they can take objects and object sets as input, read property values of objects,
> and be used across action types and applications.

Functions attach executable logic to ontology objects — not separate from the
semantic model.

### Object Views & Object Explorer

> Object Views are a central hub for all information and workflows related to a
> particular object — biographical data, linked objects, related metrics, analyses,
> dashboards, and applications.

> Object Explorer is a search and analysis tool for answering questions about
> anything in the Ontology layer.

Per-entity hub UX: one place to see everything about `Customer X` or `Project Y`.

## Architecture (how it runs)

From the Ontology system docs and object backend overview:

1. **Ontology Metadata Service (OMS)** — canonical registry of object types, link
   types, action types, interfaces, roles.
2. **Object databases** — materialized object instances indexed for query.
3. **Object Data Funnel ("Funnel")** — orchestrates writes from datasets,
   streaming sources, and user/agent **Actions** into object storage.
4. **Actions service** — applies governed edits; maintains action log for decision
   analysis.
5. **Object Set Service** — search, filter, aggregate over object sets.
6. **Ontology SDK (OSDK)** — TypeScript/Python API for apps and agents to read
   objects, traverse links, and apply actions.

Four-fold integration: **data + logic + action + security**.

Read path: high-scale SQL, real-time subscriptions, mixed human+AI teams.
Write path: atomic transactional updates, batch mutations, streams, CDC to
operational systems.

## Design principles (community / Palantir guidance)

From ontology design principles threads:

- **Design for decisions, not datasets.** Do not mirror source-system tables 1:1.
- **Object types and actions must support actual decision making.**
- **Use natural-language business concepts** — names you'd share company-wide.
- **Balance link cardinality** — meaningful links, not spiderwebs.
- **Front-end + data engineering in parallel** — placeholder objects first, fill
  backing data later (ontology-first app building).
- **Ontology is maintained like an API** — versioned, governed, not a one-time ETL
  artifact.

## What Foundry ontology is NOT

From practitioner analysis:

- Not W3C OWL/RDF/SPARQL — "inspired by" but not interoperable standard ontology.
- Not primarily a vector/memory store — objects are backed by integrated datasets
  and operational writes.
- Not lightweight — OMS, Funnel, Object Storage V2, Workshop apps, full enterprise
  stack.
- Programmatic ontology-as-code is **early** — mostly GUI Ontology Manager today;
  declarative TypeScript ontology packages exist but are not generally available.

## Comparison frame for agent-memory products

| Foundry concept | Typical agent-memory product | Gap |
| --- | --- | --- |
| Object type schema | Free-text `subject` + tags | No typed entity model |
| Property typing | JSON metadata blobs | No schema validation |
| Link types | Generic `subject-predicate-object` triples | Predicates unconstrained |
| Action types | Raw CRUD MCP tools | No governed mutation layer |
| Interfaces | None | No polymorphism across entity kinds |
| Object Views | Wiki topic pages or record lists | No unified per-entity hub |
| Decision log | Episodic timeline | Actions not first-class |
| Roles on ontology | App-level RBAC | Permissions not on entity types |
| Provenance | Dataset lineage + action log | Memory provenance partial |

## Relevance to "company brain" category

Foundry solves **operational decision-making at enterprise scale** — supply chain,
defense, healthcare ops — where agents must read state and **write back** through
governed actions.

Agent-memory products (GBrain, TeamShared) solve **institutional recall for LLM
agents** — synthesis, session distillation, skills, multi-user scoping.

Overlap:

- Both need a **semantic layer** above raw text chunks.
- Both need **typed relationships** for traversal beyond vector search.
- Both need **governed writes** when agents mutate shared state.
- Both target **human + agent** collaboration on the same concepts.

Divergence:

- Foundry starts from **integrated operational data**; memory products start from
  **conversation and documents**.
- Foundry's unit of thought is **object + action**; memory products' unit is
  **memory record + recall**.
- Foundry optimizes **write-back to enterprise systems**; memory products optimize
  **context for the next agent turn**.

## Practitioner critique (where Foundry falls short)

From Towards AI / community:

- Heavy vendor lock-in and implementation cost.
- Ontology design is hard — teams mirror bad source schemas or over-link.
- Not a good fit for small teams without operational data integration needs.
- Export/interop to standard ontologies (OWL) not supported.
- GUI-first ontology management slows CI/CD and agent-native workflows.

## Signals useful for TeamShared

1. **Nouns + verbs** — semantic graph without action types is incomplete for agents
   that need to *do* things, not just *remember*.
2. **Schema-first entities** — `Person`, `Project`, `Initiative`, `WorkItem` as
   object types beat unconstrained `subject` strings for traversal and permissions.
3. **Interfaces** — `Assignable`, `Approvable`, `Distillable` shared shapes across
   work, strategic initiatives, and memory approvals.
4. **Object Views** — console `/app/wiki/topic/{slug}` could become a true entity
   hub (memories + work + graph + episodes + approvals).
5. **Action log as product surface** — who changed what, through which governed
   action, is as valuable as the memory itself for enterprise trust.
6. **Decision-centric ontology design** — model what decisions the org makes, not
   what tables connectors ingest.
7. **Programmatic ontology** — agents should define/extend org schema via MCP, not
   a human-only GUI (TeamShared opportunity vs Foundry weakness).

## Open questions (for TeamShared validation)

1. Do design partners think in **entities and relationships** or **documents and
   chunks** when they query team memory?
2. Would typed **action types** (e.g. `approve_memory`, `assign_work`,
   `link_initiative`) reduce agent errors vs raw `memory_remember` / `work_update`?
3. Is an **org ontology** a console admin concern, emergent from distillation, or
   agent-proposed with human approval?
4. How much Foundry complexity is transferable to a 10–50 person team brain vs
   only relevant at enterprise connector scale?
