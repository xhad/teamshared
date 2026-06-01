# Plan 0
State-of-the-art AI agent memory architectures combine short-term state (working memory) with long-term semantic, episodic, and procedural storage. Advanced systems use "context engineering"—aggressive summarization, dynamic retrieval, and knowledge graphs—to give agents persistent, personalized recall without overwhelming their context windows.The 4 Pillars of AI Agent MemoryModern agent memory is typically divided into four distinct architectures:Working Memory (Short-Term): Holds immediate task instructions, current environment states, and the recent conversation history. Used for in-the-moment reasoning.Semantic Memory (Long-Term): Stores facts, user profiles, preferences, and organizational knowledge. Powered by vector databases (e.g., Pinecone) and knowledge graphs to provide rich, structured recall.Episodic Memory (Experience): Logs the agent's past experiences, past decisions, and interaction timelines. Helps the agent "learn" from past mistakes and maintain continuity across separate sessions.Procedural Memory (Skills): Stores learned rules, tool parameters, and execution logic. This allows the agent to repeatedly execute multi-step tasks without needing to be re-prompted on how to do them.State-of-the-Art Strategies"Just-in-Time" Context: Instead of keeping the entire chat history in the model's context window (which leads to "context rot"), agents use pre-inference retrieval to surface only the most relevant episodic or semantic memories right when they are needed.Aggressive Distillation: Advanced architectures (like Hindsight) use specialized sub-agents to summarize past interactions into distilled facts and preferences, rather than relying on raw transcripts.Managed Services: Solutions like Cloudflare Agent Memory provide developers with built-in primitives that extract, store, and manage user details across multi-session interactions automatically.Leading Frameworks & ToolsDevelopers typically build stateful AI agents using specialized frameworks and databases:Orchestration Libraries: LangChain and LlamaIndex offer built-in modules for both short-term conversational buffers and long-term memory RAG components.State Management: Managed databases like Databricks provide persistent architectures to track conversation history and agent states.Vector/Graph Databases: Neo4j is frequently used to build context graphs that track complex relationships between user entities and past actions.

# Plan 1

We are taking TeamShared, an agent shared-memory PoC, to production.

Please inspect the current codebase and produce a concrete implementation plan to make it production-ready for multi-tenant organization customers.

Focus on:

1. Multi-tenant org architecture

2. Tenant-safe database schema

3. Users, orgs, teams, projects, agents, roles, and permissions

4. Memory CRUD with scope-aware access control

5. Secure retrieval pipeline that applies tenant and permission filters before vector search

6. Audit logging for every memory read/write/delete/share event

7. API design for orgs, projects, agents, memory search, memory ingestion, approvals, and admin controls

8. Connector architecture for Slack, GitHub, Notion, Google Drive, Linear, and MCP servers

9. Production security controls

10. Observability, retries, background workers, queues, and failure handling

11. Migration plan from current PoC state to production architecture

Please output:

- Current-state assessment based on the codebase

- Target architecture

- Database migration plan

- API changes

- Service/module changes

- Security changes

- Engineering ticket breakdown

- Recommended implementation order

- Risk register

- Tests needed before launch

Important principles:

- Every table containing customer data must include `org_id` or be clearly tenant-owned through a parent relation.

- Every memory retrieval must be tenant-scoped before semantic search.

- Permission checks must happen before and after retrieval.

- Agents and API keys must be first-class identities with scoped permissions.

- Audit logs are mandatory.

- Memory should have source, scope, visibility, confidence, versioning, and retention metadata.

- The system must prevent cross-tenant memory leakage by design, not only by convention.