Yes bhai. This is the better approach. I went through the uploaded roadmap and reconciled it with the **actual project state we've completed through Phase 6**. The main thing is that we should **not renumber the phases**, because the existing roadmap structure is useful; instead, we update completed statuses and **redefine Phase 7 so it doesn't repeat the agent work already completed in Phase 6**.

Below is the updated `roadmap.md`. **Copy-paste this entire thing over your current `roadmap.md`**, then tell Codex only to read it and use it as the source of truth.

````markdown
# MannerAI Meetings Platform — Project Roadmap

> **Source of Truth**
>
> This document is the canonical roadmap for the entire Meeting Summarizer & Follow-Up AI Agent project.
>
> The project is being built incrementally as a production-oriented meeting intelligence platform rather than as a collection of disconnected features.
>
> Completed phases must not be rebuilt unless a deliberate architectural change is required.
>
> Future implementation must follow this roadmap and update the completion status as work progresses.
>
> **Important:** This roadmap describes both the target architecture and the actual implementation state. A target capability must not be described as implemented merely because it exists in the target architecture.

---

# 1. Project Vision

Build a scalable AI-powered Meeting Intelligence Platform that allows users to:

- authenticate securely
- create and manage meetings
- upload meeting transcripts
- generate AI summaries
- extract action items
- extract decisions
- generate follow-up emails
- generate meeting insights
- search across meetings semantically
- analyze meeting and task trends
- ask questions across historical meetings
- integrate with external services such as Gmail
- process expensive AI workloads asynchronously
- maintain observability, reliability, security, and clean API contracts

The project should demonstrate strong software engineering fundamentals alongside AI/LLM capabilities.

The goal is not simply:

> "Call an LLM and summarize a transcript."

The goal is:

> "Design and implement a maintainable, scalable meeting intelligence platform with AI as one component of the system."

---

# 2. Target System Architecture

The intended final architecture is:

```text
                         ┌──────────────────┐
                         │    React Web     │
                         │    Frontend      │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  API Gateway     │
                         │                  │
                         │ Auth / Routing   │
                         │ API Contract     │
                         └────────┬─────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                 │
                ▼                 ▼                 ▼
        ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
        │ Meeting        │ │ AI             │ │ Search         │
        │ Service        │ │ Service        │ │ Service        │
        │                │ │                │ │                │
        │ Meetings       │ │ AI Agents      │ │ Embeddings     │
        │ Transcripts    │ │ Orchestration  │ │ Semantic Search│
        │ Domain Data    │ │ Model Provider │ │ RAG            │
        └───────┬────────┘ └───────┬────────┘ └───────┬────────┘
                │                  │                  │
                └──────────────────┼──────────────────┘
                                   │
                                   ▼
                         ┌──────────────────┐
                         │ Worker Service   │
                         │                  │
                         │ Celery Jobs      │
                         │ AI Processing    │
                         │ Embeddings       │
                         └────────┬─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              PostgreSQL        Redis         Qdrant
              Persistent DB   Queue/Cache    Vector DB
````

Supporting infrastructure:

* FastAPI
* PostgreSQL
* SQLAlchemy 2.x
* Alembic
* Redis
* Celery
* Qdrant
* React
* TypeScript
* Docker
* Nginx
* LLM / embedding provider
* structured logging
* centralized exception handling
* automated tests

### Important implementation distinction

The architecture above is the **target architecture**.

As of the current project state:

* Meeting Service is implemented through the current Meeting Domain MVP.
* Gateway authentication and authenticated internal service identity are implemented.
* AI Service foundation and five agent contracts are implemented.
* Real LLM/provider execution is not yet implemented.
* AI-result persistence integration is not yet implemented.
* Worker/Celery processing is not yet implemented.
* Redis production integration is not yet implemented.
* Qdrant/Search Service is not yet implemented.
* Frontend is not yet implemented.
* Gmail integration is not yet implemented.
* Docker/platform integration remains intentionally deferred until the infrastructure stage.

---

# 3. Product Scope

## Core Inputs

The platform should eventually support:

* meeting transcript
* meeting notes
* meeting audio

Transcript processing is the first implementation target.

Audio transcription can be added later.

---

## Core Outputs

For every processed meeting, the platform should eventually support:

* Executive summary
* Action items
* Decisions
* Follow-up email
* Meeting insights
* Searchable transcript
* Embeddings
* Analytics

---

# 4. Phase 0 — Product Definition

## Status: COMPLETE

Define the product problem, scope, architecture goals, and major capabilities.

### Core MVP

* Authentication
* Meetings
* Transcripts
* AI summarization
* Action-item extraction
* Decision extraction
* Follow-up email generation
* Semantic search
* Meeting analytics

### Engineering Goals

The platform must demonstrate:

* modular architecture
* service boundaries
* clean database design
* API contracts
* background processing
* observability
* security
* testing
* documentation
* production-oriented engineering practices

---

# 5. Phase 1 — Architecture Design

## Status: COMPLETE

Architecture was designed before implementing business features.

Completed architectural areas:

* service decomposition
* gateway boundary
* shared infrastructure
* PostgreSQL persistence strategy
* API versioning strategy
* logging architecture
* exception architecture
* health/readiness strategy
* migration strategy
* testing strategy
* documentation structure

---

# 6. Phase 2 — Backend Foundation

## Status: COMPLETE

Phase 2 established the backend foundation and was completed through Phase 2.8.

---

## Phase 2.1 — Configuration Foundation

### Status: COMPLETE

Implemented:

* centralized settings
* environment-based configuration
* service-specific settings
* shared configuration
* environment validation
* database configuration
* Redis configuration scaffolding
* Qdrant configuration scaffolding
* Celery configuration scaffolding
* secret handling
* configuration tests

---

## Phase 2.2 — Centralized Logging

### Status: COMPLETE

Implemented:

* centralized logger
* development formatter
* production JSON formatter
* structured logging
* `contextvars` request context
* request IDs
* `X-Request-ID`
* request logging middleware
* service logging bootstrap
* Uvicorn integration
* sensitive-field protection
* health endpoint noise reduction

---

## Phase 2.3 — Standardized Exception & Error Handling

### Status: COMPLETE

Implemented:

* `AppError`
* common application exceptions
* centralized exception handlers
* validation error handling
* HTTP exception handling
* unexpected exception handling
* standardized error response schema
* request ID in error responses
* safe 500 responses
* traceback logging only on server side
* security-conscious error messages
* standardized 404 handling

---

## Phase 2.4 — API Design & Contract Standardization

### Status: COMPLETE

Implemented:

* `/api/v1` public API strategy
* API constants
* pagination schemas
* pagination helpers
* OpenAPI customization
* common error responses
* gateway API router
* gateway API versioning
* public response schemas
* standardized 404 envelope
* route organization
* API documentation

Public architecture:

```text
/api/v1/*
```

Infrastructure endpoints remain separate.

---

## Phase 2.5 — PostgreSQL Database Foundation

### Status: COMPLETE

Implemented:

* SQLAlchemy 2.x async architecture
* PostgreSQL
* asyncpg
* `DeclarativeBase`
* shared database package
* async engine
* connection pooling
* request-scoped `AsyncSession`
* database health check
* database lifecycle management
* Alembic
* migration environment
* UUID primary-key mixin
* timestamp mixin
* database readiness endpoint
* PostgreSQL integration testing

### Current database ownership

| Service         | PostgreSQL                                  |
| --------------- | ------------------------------------------- |
| Meeting Service | Connected                                   |
| Gateway         | Authentication/user persistence implemented |
| AI Service      | No direct persistence ownership             |
| Search Service  | Deferred                                    |
| Worker          | Deferred                                    |

Database:

```text
mannerai_meetings
```

Current development migration head:

```text
0004_meeting_domain_results
```

Migration chain:

```text
0001_meetings_transcripts
        ↓
0002_users
        ↓
0003_refresh_sessions
        ↓
0004_meeting_domain_results
```

---

## Phase 2.6 — Domain ORM Models

### Status: COMPLETE FOR CURRENT DOMAIN SCOPE

Implemented persistent models:

### User

Implemented:

* UUID identity
* normalized unique email
* password hash
* timestamps
* secure credential storage

### Meeting

Implemented:

* UUID identity
* meeting metadata
* ownership fields
* timestamps
* relationships

### Transcript

Implemented:

* UUID identity
* Meeting relationship
* transcript content
* transcript metadata
* timestamps

### Summary

Implemented:

* Meeting relationship
* summary content
* key topics
* optional provider/model metadata
* versioning
* timestamps
* unique `(meeting_id, version)`

### Task

Implemented:

* Meeting relationship
* title
* description
* nullable assignee
* due date/time
* task status
* timestamps

### Decision

Implemented:

* Meeting relationship
* statement
* optional context
* participant metadata
* timestamps

### Follow-up

Implemented:

* Meeting relationship
* subject
* HTML body
* recipient metadata
* status
* scheduling/sent timestamps
* timestamps

### MeetingInsight

Not yet persisted.

A MeetingInsight persistence model has deliberately been deferred because the project does not yet have a sufficiently clear persistence shape, cardinality, or lifecycle for insights.

Additional models should only be introduced when required by actual features.

---

# 7. Phase 2.7 — Repository Layer

## Status: COMPLETE FOR CURRENT DOMAIN SCOPE

Implemented repositories include:

* `MeetingRepository`
* `TranscriptRepository`
* `UserRepository`
* `SummaryRepository`
* `TaskRepository`
* `DecisionRepository`
* `FollowUpRepository`
* `RefreshSessionRepository`

Repository responsibility:

```text
Repository
    ↓
Database queries
```

Repositories must:

* execute database operations
* not own business logic
* not commit transactions
* not rollback transactions
* perform explicit persistence/query operations
* avoid implicit async relationship loading

Transaction ownership remains above the repository layer.

---

# 8. Phase 2.8 — Meeting Service Layer

## Status: COMPLETE FOR CURRENT MEETING + TRANSCRIPT + DOMAIN RESULT SCOPE

Implemented service architecture:

```text
Route
  ↓
Service
  ↓
Repository
  ↓
AsyncSession
  ↓
PostgreSQL
```

Implemented Meeting Service capabilities:

### Meetings

* create meeting
* get meeting
* list meetings
* update meeting
* update status

### Transcripts

* create transcript
* get transcript
* replace transcript

### Domain results

* Summary operations
* Task operations
* Decision operations
* Follow-up operations

### Service rules

* successful writes commit exactly once
* reads never commit
* failures rollback
* DTO ↔ ORM mapping is explicit
* repositories never commit
* ownership is checked before protected meeting/result operations

---

# 9. Phase 3 — Meeting API

## Status: COMPLETE

The Meeting API was implemented and is no longer the next feature.

Implemented Meeting Service and public Gateway API capabilities include:

### Meetings

```text
POST /api/v1/meetings
GET /api/v1/meetings/{meeting_id}
PATCH /api/v1/meetings/{meeting_id}
PATCH /api/v1/meetings/{meeting_id}/status
```

### Transcripts

```text
POST /api/v1/meetings/{meeting_id}/transcript
GET /api/v1/meetings/{meeting_id}/transcript
PUT /api/v1/meetings/{meeting_id}/transcript
```

### AI/domain result APIs

```text
POST /api/v1/meetings/{meeting_id}/summaries
GET  /api/v1/meetings/{meeting_id}/summaries
GET  /api/v1/meetings/{meeting_id}/summaries/latest
GET  /api/v1/meetings/{meeting_id}/summaries/{summary_id}

POST /api/v1/meetings/{meeting_id}/tasks
GET  /api/v1/meetings/{meeting_id}/tasks
GET  /api/v1/meetings/{meeting_id}/tasks/{task_id}
PATCH /api/v1/meetings/{meeting_id}/tasks/{task_id}

POST /api/v1/meetings/{meeting_id}/decisions
GET  /api/v1/meetings/{meeting_id}/decisions
GET  /api/v1/meetings/{meeting_id}/decisions/{decision_id}

POST /api/v1/meetings/{meeting_id}/followups
GET  /api/v1/meetings/{meeting_id}/followups
GET  /api/v1/meetings/{meeting_id}/followups/{followup_id}
PATCH /api/v1/meetings/{meeting_id}/followups/{followup_id}
```

Routes remain thin and delegate to services.

### Deferred Meeting list work

A fully public organization-wide Meeting list contract remains intentionally deferred.

Reason:

* organization membership model is not yet implemented
* client-supplied `organization_id` alone is insufficient for safe authorization
* no safe public membership-aware list contract exists yet

Search and client-selected sorting for meetings are also deferred until the domain/repository contract defines the required behavior.

---

# 10. Phase 4 — Authentication & Authorization

## Status: COMPLETE

Authentication and authorization are implemented.

### User authentication

Implemented:

* signup
* login
* password hashing
* JWT access tokens
* current-user dependency
* protected routes
* authenticated user self-service

### Access JWT

Implemented with:

* UUID subject
* access-token type
* issued-at claim
* expiration
* configured issuer/audience where applicable
* secure signing configuration

Passwords and password hashes are never exposed through public response schemas.

### Refresh sessions

Implemented:

* opaque refresh tokens
* cryptographically secure random generation
* SHA-256 hash persistence
* independent refresh sessions
* refresh-token rotation
* old-token revocation
* logout revocation
* concurrent refresh protection using database row locking
* generic invalid-token handling

### User self-service

Implemented:

```text
GET   /api/v1/auth/me
GET   /api/v1/users/me
PATCH /api/v1/users/me
```

The update contract intentionally does not expose password/password_hash modification through this endpoint.

### Gateway → Meeting Service security boundary

Implemented:

```text
External Client
      ↓
Gateway
      ↓
Authenticated external JWT
      ↓
Short-lived internal principal JWT
      ↓
Meeting Service
```

Internal service identity uses asymmetric signing:

```text
Gateway
  └── internal principal private key

Meeting Service
  └── internal principal public key
```

Meeting Service does not trust a client-supplied identity header and does not directly accept the external access JWT as its internal identity mechanism.

### Ownership authorization

Protected Meeting/result operations verify authenticated ownership before access or modification.

---

# 11. Phase 5 — Complete Meeting Domain / Meeting Service MVP

## Status: COMPLETE

Phase 5 completed the current Meeting Domain MVP.

Implemented:

* User persistence
* Summary model
* Task model
* Decision model
* Follow-up model
* repositories
* services
* migrations
* API schemas
* validation
* relationships
* public Gateway result routes
* ownership enforcement
* PostgreSQL persistence verification

### Migration

Current head:

```text
0004_meeting_domain_results
```

Validation confirmed:

* Meeting persistence
* Transcript persistence
* Summary persistence
* Task persistence
* Decision persistence
* Follow-up persistence
* Summary version uniqueness
* Summary latest-version ordering
* Task status filtering
* Follow-up status filtering
* Task assignee `ON DELETE SET NULL`
* Meeting child `ON DELETE CASCADE`

### Important Phase 5 decisions

MeetingInsight persistence remains deferred.

Public organization-wide Meeting listing remains deferred until organization membership/authorization is defined.

Meeting search/client-selected sorting remains deferred until a clear domain/repository contract exists.

---

# 12. Phase 6 — AI Service Foundation

## Status: COMPLETE

Phase 6 established the independent AI Service foundation.

Create/maintain:

```text
backend/ai-service/
```

### Core AI Service components

```text
app/
agents/
llm/
```

### Processing contracts

Implemented:

* `ProcessingRequest`
* `ProcessingResult`
* requested operations
* meeting/transcript identity validation
* optional processing context
* typed operation results
* operation-level success/failure
* aggregate processing status

### Provider abstraction

Implemented:

* `ModelProvider` protocol
* provider-neutral `ModelRequest`
* provider-neutral `ModelResponse`
* sanitized provider error categories
* injected model providers
* structured-output validation
* timeout/unexpected provider failure handling
* malformed model output handling

A real provider client is intentionally deferred.

### Common Agent architecture

Implemented:

* common Agent abstraction
* `AgentKind`
* typed `AgentInput`
* transcript content/segment contracts
* injected `ModelProvider`
* shared structured-output validation

Agents:

* receive transcript content from their caller
* do not access SQLAlchemy directly
* do not access PostgreSQL directly
* do not own persistence
* do not resolve database users
* do not send external communications

### Implemented AI agents

#### SummaryAgent

Produces:

* summary content
* key topics

Does not expose persistence IDs, version metadata, timestamps, or database relationships.

#### TaskAgent

Produces zero or more task candidates:

* title
* optional description
* optional transcript-level assignee name
* optional explicit/unambiguous calendar due date

Does not resolve names into User IDs.

Task lifecycle status remains application/persistence logic.

#### DecisionAgent

Produces zero or more decision candidates:

* statement
* optional context
* participant names

Distinguishes decisions from proposals, questions, unresolved options, and general discussion.

#### FollowUpAgent

Produces zero or more follow-up drafts:

* subject
* HTML body
* transcript-supported recipient references

Does not:

* send email
* manage delivery status
* schedule sending
* resolve recipients to database user IDs

#### InsightAgent

Produces zero or more typed insights.

Supported categories:

* risk
* blocker
* concern
* opportunity
* dependency
* unresolved
* disagreement
* observation

Insights are transcript-grounded and conservative.

### Source-data / prompt boundary

Transcript content is treated as untrusted source material rather than instructions.

Agents are designed to:

* remain grounded in transcript content
* avoid invented facts
* preserve uncertainty
* avoid unsupported assignees
* avoid unsupported deadlines
* avoid unsupported recipients
* distinguish tasks from decisions
* distinguish decisions from proposals/questions
* distinguish follow-ups from tasks
* allow empty results where appropriate

Typed schemas and prompts provide structural and behavioral guardrails but do not guarantee perfect semantic grounding.

### Orchestration

Implemented orchestrator behavior:

* explicit operation → explicit agent routing
* deterministic sequential processing
* request deduplication
* order preservation
* meeting/transcript identity validation
* typed per-operation results
* partial-failure preservation
* distinction between partial and total failure
* sanitized operation-level errors

Persistence is intentionally not part of the Phase 6 orchestrator.

### Phase 6 hardening

One concrete contract issue was found during adversarial review:

`ProcessingRequest` deduplicated requested operations, but `ProcessingResult` could still be directly constructed with duplicate operations/outcomes.

The result contract was hardened with a uniqueness invariant and regression coverage.

This issue is documented in the engineering/problem-solving log.

### Phase 6 deferred work

* real `ModelProvider` implementation
* provider-specific client integration
* real LLM execution
* AI output → Meeting Service domain mapping
* MeetingInsight persistence design
* background processing
* Redis/Celery integration
* production AI pipeline
* Docker/infrastructure integration
* later roadmap phases

---

# 13. Phase 7 — AI Meeting Intelligence Integration

## Status: NEXT

Phase 7 builds the **actual meeting intelligence pipeline on top of the completed Phase 6 AI foundation**.

Important:

The five agents already exist.

Phase 7 must **not rebuild the agents**.

Instead, Phase 7 integrates the existing agents with real model execution, transcript processing, validation, and Meeting Service persistence boundaries.

### Primary goal

Move from:

```text
Transcript
    ↓
Typed Agent Architecture
    ↓
Typed AI Output
```

to:

```text
Transcript
    ↓
Real Model Provider
    ↓
AI Orchestrator
    ↓
Summary / Tasks / Decisions / Follow-ups / Insights
    ↓
Validated Domain Candidates
    ↓
Meeting Service Persistence
```

### Phase 7.1 — Real Model Provider

Implement the first real `ModelProvider`.

Requirements:

* provider-specific implementation behind the existing provider abstraction
* no provider-specific logic inside agents
* configuration through service settings
* timeout handling
* controlled error handling
* model configuration
* secure credential handling
* provider response normalization
* structured-output validation

The provider implementation must preserve the existing provider-neutral contracts.

Do not couple the agents directly to an SDK.

---

### Phase 7.2 — Transcript Processing Integration

Define and implement the real mapping from stored transcript data to `AgentInput`.

Flow:

```text
Meeting / Transcript
        ↓
Transcript Retrieval
        ↓
AgentInput
        ↓
AI Orchestrator
        ↓
Agent Outputs
```

Requirements:

* deterministic transcript serialization
* preserve speaker information
* preserve timestamps where available
* preserve language/segment metadata where applicable
* reject missing/invalid transcript content
* avoid giving agents direct database access

---

### Phase 7.3 — AI Output Validation & Domain Mapping

Build the boundary between AI output contracts and Meeting Service domain models.

```text
AI Output
   ↓
Validation / Normalization
   ↓
Domain DTO
   ↓
Meeting Service
   ↓
Repository
   ↓
PostgreSQL
```

Implement mapping for:

* Summary
* Task
* Decision
* Follow-up

Important boundaries:

* AI candidates are not ORM objects
* agents do not create database records
* user-name resolution happens outside agents
* task status is assigned by application logic
* persistence metadata is assigned by the domain/application layer
* AI-generated content must not bypass domain validation

### Task mapping

The AI `due_date` field must be mapped deliberately into the domain Task due-time representation.

### Assignee mapping

Transcript-level `assignee_name` must not be treated as a User UUID.

Resolution should occur through an explicit application/domain boundary.

If resolution is ambiguous, the system must preserve the ambiguity rather than inventing a user.

### Follow-up recipient mapping

Recipient names/emails must be resolved/validated outside the agent.

Do not automatically treat arbitrary transcript text as a deliverable recipient.

---

### Phase 7.4 — MeetingInsight Persistence Design

Before creating a MeetingInsight ORM model, determine:

* persistence shape
* cardinality
* lifecycle
* categories
* versioning requirements
* relationship to Meeting
* whether insights are snapshots, regenerated results, or independently managed records
* API requirements
* replacement/versioning behavior

Only after the design is clear should a migration/model/repository/service be introduced.

Do not create a speculative MeetingInsight table simply to match the agent output.

---

### Phase 7.5 — AI Processing Service Contract

Define the service-level processing contract between Meeting Service and AI Service.

Determine:

* synchronous vs internal invocation semantics
* request contract
* response contract
* operation selection
* validation
* error semantics
* request correlation
* authentication between services
* timeout behavior

This phase should prepare the AI pipeline for later asynchronous Worker/Celery integration without prematurely implementing background processing.

---

### Phase 7.6 — AI Integration Testing

Add tests covering:

* real provider adapter behavior through controlled mocks/fakes
* provider timeout/error handling
* structured model output validation
* transcript → AgentInput mapping
* agent → domain output mapping
* task due-date mapping
* assignee resolution boundaries
* follow-up recipient validation
* MeetingInsight design/behavior once persistence exists
* partial AI failures
* invalid model output
* request/response identity consistency
* security boundaries

PostgreSQL integration tests should cover persistence once the mapping layer is implemented.

Do not require external provider credentials for the normal test suite.

---

# 14. Phase 8 — Background Processing

## Status: NOT STARTED

AI processing must not block normal HTTP requests.

Target flow:

```text
Upload Transcript
       ↓
Create/Update Meeting
       ↓
Queue Processing Job
       ↓
Redis
       ↓
Celery Worker
       ↓
AI Service
       ↓
Validate / Map Results
       ↓
Persist Results
```

Implement jobs such as:

```text
summary_job.py
task_job.py
decision_job.py
followup_job.py
embedding_job.py
```

Handle:

* retries
* failures
* idempotency
* job status
* duplicate processing prevention
* task timeouts
* safe failure recovery

Phase 8 should consume the synchronous AI intelligence pipeline established in Phase 7 rather than duplicating AI logic.

---

# 15. Phase 9 — Redis & Celery Production Integration

## Status: NOT STARTED

Implement:

* Redis connection
* Celery application
* task queue
* worker configuration
* retry policies
* task timeouts
* failure handling
* task status tracking
* worker health/readiness
* job lifecycle persistence where appropriate

The Worker Service should become a real background-processing service rather than infrastructure scaffolding.

---

# 16. Phase 10 — Vector Search & RAG

## Status: NOT STARTED

Introduce Qdrant.

Pipeline:

```text
Transcript
   ↓
Chunking
   ↓
Embedding Model
   ↓
Vector
   ↓
Qdrant
```

Search:

```text
User Query
   ↓
Query Embedding
   ↓
Qdrant
   ↓
Top-K Relevant Chunks
   ↓
Meeting Context
   ↓
AI / RAG
   ↓
Answer
```

Support:

* semantic meeting search
* similar meetings
* transcript retrieval
* cross-meeting question answering

Example:

> "What did we decide about the project budget?"

The system should retrieve the relevant historical meeting context.

---

# 17. Phase 11 — Search Service

## Status: NOT STARTED

Implement the independent Search Service.

Responsibilities:

* indexing
* embedding lookup
* semantic search
* similarity search
* RAG retrieval
* cross-meeting retrieval

Do not duplicate search logic inside Meeting Service.

---

# 18. Phase 12 — Cross-Meeting Intelligence

## Status: NOT STARTED

Support questions such as:

> What recurring issues appeared this month?

> Which projects repeatedly missed deadlines?

> What decisions were made about Project X?

> Which action items are still unresolved?

Use:

```text
PostgreSQL
+
Qdrant
+
LLM
+
RAG
```

This is one of the major differentiating capabilities of the project.

---

# 19. Phase 13 — Analytics

## Status: NOT STARTED

Implement analytics APIs.

Dashboard metrics:

* total meetings
* meetings per week
* open tasks
* completed tasks
* overdue tasks
* decisions
* follow-ups
* processing status

Advanced analytics:

* topic trends
* recurring blockers
* decision trends
* task completion trends
* meeting frequency
* speaker participation

---

# 20. Phase 14 — Frontend

## Status: NOT STARTED

Build React + TypeScript frontend.

Build in this order.

### Authentication

Pages:

* Login
* Signup

### Dashboard

Cards:

* Total Meetings
* Open Tasks
* Completed Tasks
* Decisions
* Upcoming Follow-ups

### Meetings

Table:

* Title
* Date
* Status
* Processing Status

### Meeting Details

Tabs:

```text
Transcript
Summary
Tasks
Decisions
Insights
Follow-up
```

### Upload

Support:

* transcript upload
* meeting metadata
* processing status
* processing progress

### Search

Semantic search interface:

```text
"What did we decide about hiring?"
```

Show:

* relevant meetings
* transcript snippets
* similarity/relevance
* source meeting

### Analytics

Charts:

* meetings/week
* tasks completed
* open vs completed tasks
* decisions over time
* recurring topics

---

# 21. Phase 15 — Gateway Integration

## Status: PARTIALLY COMPLETE

The Gateway is already the public API boundary for implemented authentication and Meeting/domain APIs.

Already implemented:

* authentication boundary
* public API versioning
* request routing for implemented APIs
* standardized errors
* request correlation
* authenticated identity propagation
* Gateway → Meeting Service internal principal boundary

Remaining work:

* expose future Search APIs
* expose future processing/job APIs
* expose future analytics APIs
* expose future cross-meeting intelligence APIs
* integrate future frontend-facing contracts
* harden service-to-service communication as additional services become active

Target:

```text
Frontend
   ↓
Gateway
   ↓
Internal Services
```

Internal service APIs remain separate from public API contracts.

---

# 22. Phase 16 — Gmail Integration

## Status: NOT STARTED

Implement:

```text
Generate Email
      ↓
User Reviews
      ↓
User Confirms
      ↓
Gmail API
      ↓
Send Email
```

Never automatically send generated emails without explicit user confirmation.

Track:

* draft
* approved
* sent
* failed

---

# 23. Phase 17 — Production Quality

## Status: PARTIALLY COMPLETE

### Already implemented

* centralized logging
* structured logging
* request IDs
* exception handling
* validation
* API versioning
* health checks
* readiness checks
* OpenAPI
* PostgreSQL pooling
* Alembic
* test infrastructure
* authentication
* authorization/ownership checks for implemented protected resources
* security-conscious error handling
* internal service identity boundary

### Remaining

#### Reliability

* retries
* idempotency
* graceful degradation
* dependency failure handling
* worker failure recovery
* AI provider failure recovery

#### Observability

* processing metrics
* job metrics
* AI latency
* database latency
* request latency
* error rates
* provider metrics

#### Security

* rate limiting
* secret management hardening
* safe logging review
* secure CORS configuration
* service-to-service authentication hardening
* AI input/output security
* prompt-injection resilience
* provider credential protection

#### Performance

* database indexes
* query optimization
* pagination
* async I/O
* caching where appropriate
* efficient vector retrieval
* AI request optimization

---

# 24. Phase 18 — Testing

## Status: ONGOING

Maintain multiple test layers.

### Unit Tests

Test:

* configuration
* schemas
* services
* repositories
* AI components
* utilities
* provider adapters
* mapping logic

### Integration Tests

Test:

* PostgreSQL
* Redis
* Qdrant
* service interactions
* persistence mappings
* Worker/AI integration

### API Tests

Test:

* authentication
* CRUD
* validation
* error contracts
* authorization
* AI processing APIs
* job APIs
* search APIs

### End-to-End Tests

Eventually test:

```text
Signup
 ↓
Login
 ↓
Create Meeting
 ↓
Upload Transcript
 ↓
Queue Processing
 ↓
AI Processing
 ↓
Summary / Tasks / Decisions
 ↓
Search
 ↓
Generate Follow-up
 ↓
Review
 ↓
Send Email
```

Testing should continue throughout implementation rather than being postponed to the end.

---

# 25. Phase 19 — Docker & Local Platform

## Status: DEFERRED

Docker/platform integration is intentionally deferred until the infrastructure stage.

Eventually Docker Compose should run:

```text
frontend
gateway
meeting-service
ai-service
search-service
worker-service
postgresql
redis
qdrant
nginx
```

The entire platform should eventually be startable with a single command.

Important:

Do not modify Docker/Compose during earlier feature phases unless a deliberate architectural decision changes this roadmap.

---

# 26. Phase 20 — Infrastructure & Deployment

## Status: NOT STARTED

Prepare deployment architecture.

Consider:

* Docker images
* environment configuration
* reverse proxy
* HTTPS
* database migrations
* service health checks
* secrets
* logging
* monitoring
* CI/CD

Deployment should be reproducible.

---

# 27. Phase 21 — Resume-Level AI Enhancements

## Status: NOT STARTED

Add advanced intelligence only after the core platform is stable.

### Speaker Analytics

Determine:

* who spoke most
* speaking distribution
* participation balance

### Sentiment

Analyze:

* positive
* neutral
* negative
* changes during meeting

### Risk Extraction

Identify:

* blockers
* risks
* unresolved concerns
* dependencies

### Deadline Intelligence

Identify:

* upcoming deadlines
* overdue tasks
* task urgency

### Recurring Issue Detection

Across multiple meetings:

* recurring blockers
* repeated topics
* unresolved decisions
* recurring risks

---

# 28. Phase 22 — Documentation

## Status: ONGOING

Maintain:

```text
README.md

docs/
├── architecture/
├── api/
├── database/
├── engineering/
├── study/
└── ...
```

Documentation must cover:

* project overview
* architecture
* service responsibilities
* API contracts
* database design
* migrations
* logging
* exceptions
* authentication
* authorization
* AI pipeline
* RAG pipeline
* background processing
* deployment
* local setup
* testing
* important engineering decisions
* known limitations
* deferred work

Important architectural decisions should be documented with the reasoning behind them.

Documentation checkpoints should occur after meaningful implementation blocks rather than only at the end of the project.

---

# 29. Phase 23 — Engineering / Problem-Solving Log

## Status: ONGOING

Maintain a dedicated engineering log documenting significant implementation problems.

For each major issue record:

```text
Problem
Symptoms
Investigation
Root Cause
Solution
Validation
Engineering Lesson
```

This is important because the project should demonstrate:

> engineering decisions and debugging ability

rather than appearing to have been generated entirely by an AI coding tool.

Update this log at meaningful project checkpoints.

Only document real issues encountered during implementation.

---

# 30. Phase 24 — Portfolio Preparation

## Status: NOT STARTED

Before declaring the project complete:

### README

Include:

* problem
* solution
* architecture
* features
* screenshots
* API documentation
* setup
* tech stack
* engineering decisions
* known limitations

### Architecture Diagram

Create a professional system architecture diagram.

### Demo

Create a 3–5 minute demonstration showing:

1. Signup/login
2. Create meeting
3. Upload transcript
4. Processing begins
5. AI summary
6. Tasks
7. Decisions
8. Follow-up email
9. Semantic search
10. Cross-meeting intelligence
11. Analytics

---

# 31. Final Target User Flow

The completed product should eventually support:

```text
User
 ↓
Signup / Login
 ↓
Dashboard
 ↓
Create Meeting
 ↓
Upload Transcript
 ↓
Meeting Stored
 ↓
Processing Job Queued
 ↓
Celery Worker
 ↓
AI Orchestrator
 ├── Summary Agent
 ├── Task Agent
 ├── Decision Agent
 ├── Follow-up Agent
 └── Insight Agent
 ↓
Validated AI Outputs
 ↓
Domain Mapping
 ↓
Results Stored
 ↓
Embeddings Generated
 ↓
Qdrant
 ↓
Meeting Available for Search
 ↓
User Searches Historical Meetings
 ↓
RAG Retrieval
 ↓
AI Answer
 ↓
User Reviews Follow-up Email
 ↓
Gmail
 ↓
Email Sent
```

The above is the **final target flow**, not the current implementation state.

---

# 32. Architectural Principles

Throughout the project:

### 1. Build architecture before features

Do not introduce feature code that violates established boundaries.

### 2. Keep services focused

Each service should have a clear responsibility.

### 3. Keep domain logic out of routes

Preferred:

```text
Route
 ↓
Service
 ↓
Repository
 ↓
Database
```

### 4. Keep ORM models separate from API schemas

Never expose database models directly as public API contracts.

### 5. Repositories do not own transactions

Transaction boundaries belong to the service layer.

### 6. Do not block HTTP requests with expensive AI work

Use background jobs once the background-processing phase is implemented.

### 7. Do not make AI the architecture

AI is a subsystem within the platform.

### 8. Keep AI agents independent from persistence

Agents should operate on typed inputs and produce typed outputs.

Agents must not directly access SQLAlchemy sessions or database repositories.

### 9. Keep provider-specific code behind an abstraction

Agents must not depend directly on a provider SDK.

### 10. Treat external/transcript content as untrusted source data

AI prompts must not treat transcript content as trusted instructions.

### 11. Prefer real implementations over fake endpoints

Do not create placeholder business APIs merely to make the project appear complete.

### 12. Test every major architectural layer

New features should include appropriate tests.

### 13. Document important engineering decisions

The repository should explain not only what was built, but why.

### 14. Do not rebuild completed phases

Existing implementations should be reused unless a deliberate architectural change is required.

### 15. Defer infrastructure until the architecture requires it

Do not prematurely introduce Docker, Redis, Celery, Qdrant, or deployment complexity before their corresponding feature phase.

---

# 33. Current Project Status

## Completed

* Product definition
* Architecture design
* Configuration foundation
* Centralized logging
* Request correlation
* Exception handling
* API contract foundation
* API versioning
* Pagination foundation
* PostgreSQL foundation
* Async SQLAlchemy
* Database health/readiness
* Alembic foundation
* Meeting ORM model
* Transcript ORM model
* User ORM model
* Summary ORM model
* Task ORM model
* Decision ORM model
* Follow-up ORM model
* Meeting migration
* Transcript migration
* User migration
* Refresh session migration
* Meeting domain result migration
* Meeting repository
* Transcript repository
* User repository
* Summary repository
* Task repository
* Decision repository
* Follow-up repository
* Refresh session repository
* Meeting service
* Transcript service operations
* Meeting domain result services
* Authentication
* JWT access tokens
* Refresh-token lifecycle
* Logout
* Current-user self-service
* Gateway authentication boundary
* Internal service principal authentication
* Meeting ownership authorization
* Meeting API
* Transcript API
* Summary API
* Task API
* Decision API
* Follow-up API
* PostgreSQL integration verification
* Meeting Domain MVP
* AI Service foundation
* Model provider abstraction
* Common AI agent architecture
* Summary Agent
* Task Agent
* Decision Agent
* Follow-up Agent
* Insight Agent
* AI orchestration
* Typed AI processing results
* AI partial-failure semantics
* AI source-data/prompt boundary
* AI foundation security/hardening
* Phase 6 documentation

## Current Phase

```text
Phase 7 — AI Meeting Intelligence Integration
```

## Current immediate objective

Move from the completed AI foundation:

```text
Transcript
    ↓
Typed Agent Architecture
    ↓
Typed AI Output
```

to an actual integrated intelligence pipeline:

```text
Stored Transcript
    ↓
Transcript → AgentInput
    ↓
Real Model Provider
    ↓
AI Orchestrator
    ↓
Summary / Tasks / Decisions / Follow-ups / Insights
    ↓
AI Output Validation
    ↓
Domain Mapping
    ↓
Meeting Service
    ↓
PostgreSQL
```

---

# 34. Roadmap Progression

The current progression is:

```text
Phase 0
Product Definition
        ↓
Phase 1
Architecture Design
        ↓
Phase 2
Backend Foundation
        ↓
Phase 3
Meeting API
        ↓
Phase 4
Authentication & Authorization
        ↓
Phase 5
Complete Meeting Domain
        ↓
Phase 6
AI Service Foundation
        ↓
CURRENT
Phase 7
AI Meeting Intelligence Integration
        ↓
Phase 8
Background Processing
        ↓
Phase 9
Redis & Celery
        ↓
Phase 10
Vector Search & RAG
        ↓
Phase 11
Search Service
        ↓
Phase 12
Cross-Meeting Intelligence
        ↓
Phase 13
Analytics
        ↓
Phase 14
Frontend
        ↓
Phase 15
Gateway Integration Expansion
        ↓
Phase 16
Gmail Integration
        ↓
Phase 17
Production Quality
        ↓
Phase 18
Testing / E2E Expansion
        ↓
Phase 19
Docker & Local Platform
        ↓
Phase 20
Infrastructure & Deployment
        ↓
Phase 21
Advanced AI Enhancements
        ↓
Phase 22
Documentation
        ↓
Phase 23
Engineering / Problem-Solving Log
        ↓
Phase 24
Portfolio Preparation
```

---

# 35. Definition of Done

The project should not be considered complete merely because the AI produces summaries.

The project is complete when:

* users can authenticate
* users can securely manage meetings
* transcripts can be uploaded and retrieved
* AI processing is asynchronous
* summaries are generated
* tasks are extracted
* decisions are extracted
* follow-up emails are generated
* insights are generated
* users can review/send emails
* meetings can be searched semantically
* historical meetings can be queried through RAG
* analytics are available
* services communicate through defined boundaries
* PostgreSQL persists core domain data
* Redis/Celery handle background processing
* Qdrant handles vector retrieval
* APIs are versioned and documented
* errors are standardized
* requests are traceable
* tests cover critical functionality
* Docker can reproduce the platform
* documentation explains the architecture
* the repository demonstrates meaningful engineering decisions
* production-oriented security and reliability requirements have been addressed

---

# 36. Roadmap Rule

When starting a new implementation session:

1. Read this roadmap.
2. Identify the current phase.
3. Inspect the existing implementation.
4. Do not rebuild completed work.
5. Implement only the next logical increment.
6. Test the implementation continuously.
7. Perform manual verification where appropriate.
8. Update documentation at meaningful checkpoints.
9. Update the engineering/problem-solving log when a meaningful issue was encountered.
10. Update this roadmap's status when a phase/checkpoint changes state.
11. Do not mark deferred work as complete.
12. Do not claim target architecture components are implemented until they actually exist and are validated.
13. Commit completed implementation checkpoints only after review.
14. Keep `roadmap.md` synchronized with the actual project state.

This roadmap is the project's source of truth.

---

# 37. Current Implementation Boundary

At the current point in the project:

```text
                    IMPLEMENTED
                         │
                         ▼
              ┌─────────────────────┐
              │    React Frontend   │
              │      (Future)       │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │    API Gateway      │
              │                     │
              │ Auth                │
              │ Public API          │
              │ Internal Identity   │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   Meeting Service   │
              │                     │
              │ Meetings            │
              │ Transcripts         │
              │ Domain Results      │
              │ Persistence         │
              └──────────┬──────────┘
                         │
                         ▼
                    PostgreSQL


              ┌─────────────────────┐
              │     AI Service      │
              │                     │
              │ Agent Architecture  │
              │ 5 Agents            │
              │ Orchestrator        │
              │ Provider Abstraction│
              └──────────┬──────────┘
                         │
                         │ NEXT: Phase 7
                         ▼
              ┌─────────────────────┐
              │ Real Model Provider │
              │ Transcript Mapping  │
              │ Domain Mapping      │
              │ AI Persistence      │
              └─────────────────────┘


                    FUTURE
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
     Worker          Search          Frontend
   Redis/Celery      Qdrant         React/TS
        │              │
        └───────┬──────┘
                ▼
          Full Platform
```

The next implementation work must begin from the **current AI Service foundation** and must not rebuild completed Meeting, Authentication, Domain, or Agent architecture.

```


