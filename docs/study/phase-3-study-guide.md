# Phase 3 Study and Interview Guide

## Current elevator pitch

MannerAI is a microservice-oriented meeting-intelligence platform. Through
Phase 3.4, its implemented vertical slice is persistence for meetings and
transcripts plus internal create/get meeting routes: PostgreSQL schema,
SQLAlchemy models, async repositories, service use cases, and a thin FastAPI
adapter. These are not public gateway APIs or an AI-processing workflow.

## Architecture to explain

```
Pydantic request/domain DTO
        ↓ explicit conversion
MeetingService (use case and commit boundary)
        ↓ UUIDs and ORM entities
Repository (select/add/flush)
        ↓ request-scoped AsyncSession
PostgreSQL
```

`get_db_session()` supplies the request-scoped session. It rolls back if an
exception escapes. A successful write is committed by `MeetingService`; reads
do not commit. That split lets a future use case write a meeting and transcript
atomically without each repository finalizing its own transaction.

## Concepts: what, project use, alternative, later direction

| Concept | What / how this project uses it | Alternative and why not now | Later consideration |
|---|---|---|---|
| PostgreSQL | Transactional relational store for the meeting domain. | A document store would fit raw JSON, but foreign keys, transactions, and controlled schema evolution matter here. | Add user/organization tables and foreign keys. |
| SQLAlchemy ORM / DeclarativeBase | `Base` declares mapped classes; `Meeting`/`Transcript` map Python fields to PostgreSQL columns. | Handwritten SQL is possible, but ORM typing and shared metadata support maintainability/Alembic. | Use SQL selectively for specialized queries. |
| UUID primary keys | `UUIDPrimaryKeyMixin` generates UUIDs; IDs cross repository boundaries as `uuid.UUID`. | Integer IDs are simpler but easier to enumerate and less convenient across services. | Decide UUID generation/ordering strategy if scale demands it. |
| Timestamp mixin | `TimestampMixin` defines timezone-aware creation/update timestamps. | App-generated timestamps could drift; server defaults give a database baseline. | Audit update semantics and clock assumptions. |
| JSONB | `participants` and structured transcript `segments` are JSONB. | Normalized child tables are better for heavy relational querying. | Normalize transcript segments if their size/query needs justify it. |
| Native PostgreSQL ENUM | `meeting_status` stores `pending`, `processing`, `ready`, `failed`. | Text plus a check constraint is more flexible, but native enum expresses a controlled lifecycle. | Add migrations carefully if states evolve. |
| One-to-one relationship | `Transcript.meeting_id` is unique; ORM uses `uselist=False`; deletion cascades. | One-to-many supports transcript versions, which are not a current requirement. | Revisit if multiple transcript sources/versions are needed. |
| Cascade deletion | Database FK is `ON DELETE CASCADE`; ORM also uses `delete-orphan`. | Manual deletion is error-prone. | Confirm ownership rules before adding alternate transcript references. |
| Alembic migrations | Revision `0001_meetings_transcripts` creates the current domain schema and reverses it in dependency order. | Creating tables at app startup is unsafe and untraceable. | Add reviewed migrations per intentional schema change. |
| AsyncSession / async SQLAlchemy | Repositories use `select`, `await session.execute`, `scalar_one_or_none`, `add`, and `flush`. | Synchronous sessions block an async request path. | Keep relationships explicitly loaded when future code needs them. |
| Repository pattern | Repositories isolate data access and return ORM entities. | Services issuing SQL directly mix application decisions with persistence. | Add query methods only when concrete use cases demand them. |
| Service/use-case pattern | `MeetingService` validates IDs, maps types, enforces create/replace semantics, and commits writes. | Route handlers could do this, but then HTTP concerns leak into business coordination. | Add route dependencies that construct the service. |
| Dependency injection | A future route receives `get_db_session()` and supplies it to repositories/service. | Global sessions are unsafe across requests. | Consider a Unit of Work only when its complexity earns its keep. |
| Flush vs commit vs rollback | Flush synchronizes pending SQL inside a transaction; commit makes it durable; dependency rollback cleans failures. | Repository commits would split one business transaction. | Add explicit transaction abstractions only for complex workflows. |
| DTO versus ORM | Pydantic models are API/domain contracts; ORM models are persistence mappings. | `from_attributes=True` could reduce mapping code but hides conversions and does not solve different enums. | Reassess only when contracts and persistence align deliberately. |
| UUID/enum/segment conversion | Service converts string UUIDs, `.value` between status enums, and `TranscriptSegment.model_dump()` to JSON dictionaries. | Passing raw data downward weakens type boundaries. | Consolidate enum ownership only after deciding layer ownership. |
| Pagination and ordering | Repository takes `limit`/`offset`, filters organization UUID, orders `created_at DESC, id DESC`. | Unordered pages can shift nondeterministically. | Add count/page DTO integration with routes. |
| Errors | Bad UUID → `ValidationError`; absent meeting/transcript → `NotFoundError`; duplicate transcript → `ConflictError`. | Raw database errors are not client contracts. | Translate database uniqueness races at the boundary when concurrency is addressed. |
| Transcript semantics | Create checks meeting then duplicate; replace requires an existing transcript and replaces segments/language. | `ON CONFLICT` upsert would blur create vs replace semantics. | Introduce upsert only if a justified workflow needs it. |

## Runtime details worth being able to explain

### `async_sessionmaker`: engine → factory → request session

`async_sessionmaker` is a reusable, process-level factory for `AsyncSession`
objects. The meeting-service lifecycle creates one async engine, then
`configure_session_factory(engine)` stores one factory configured with
`expire_on_commit=False`. `get_db_session()` calls that factory for each request
and yields a fresh request-scoped `AsyncSession`.

At runtime the flow is: engine manages pooled connections → the factory creates
a session for one request/use case → repositories execute through that session
→ the service commits a successful write or an escaping exception causes the
dependency to roll back → the session context closes. We do not create a new
factory on every request because factories are configuration/pooling setup,
while sessions are the short-lived units of work. A global session would be
unsafe across concurrent requests.

An interviewer may ask, “Why have both an engine and an async session maker?”
Answer: the engine owns database connectivity/pooling; the factory consistently
creates correctly configured sessions; each `AsyncSession` tracks one unit of
work.

### `values_callable`: lowercase PostgreSQL enum labels

Python's ORM enum has member names such as `PENDING`, but this project needs
the native PostgreSQL `meeting_status` labels `pending`, `processing`, `ready`,
and `failed`. `SQLEnum(MeetingStatus)` can otherwise use enum member names.
The ORM therefore declares:

```python
values_callable=lambda enum_cls: [member.value for member in enum_cls]
```

That tells SQLAlchemy to persist/use each lowercase `.value`, matching both the
migration-created PostgreSQL enum and the database server default `'pending'`.
Without it, ORM persistence could use uppercase member names and disagree with
the PostgreSQL enum labels, causing writes or schema expectations to fail.

An interviewer may ask, “Why did you need `values_callable` on the SQLAlchemy
Enum?” Answer: it makes Python enum representation and the exact persisted
PostgreSQL labels agree rather than relying on SQLAlchemy's member-name default.

### Mock-based unit tests and opt-in integration testing

Repository tests simulate `AsyncSession.execute()` and `flush()`; service tests
simulate repository results and `AsyncSession.commit()`. This verifies unit
contracts: query construction intent, entity updates, explicit DTO/ORM mapping,
errors, and exactly where commits occur. It is fast and deterministic because a
running PostgreSQL instance is not required for every test.

The tradeoff is that mocks do not establish real PostgreSQL behavior. The
separate integration test is opt-in (`RUN_POSTGRES_INTEGRATION=1`) and is
skipped by the default suite; it validates the real database path when the
environment is intentionally available. Unit tests verify behavior/contracts;
the integration test verifies actual database behavior. Both are necessary,
neither substitutes for the other.

An interviewer may ask, “Why mock database code?” Answer: to isolate fast
layer-level behavior from infrastructure availability, while retaining a
separate opt-in integration check for the real driver/database boundary.

### FastAPI dependency injection and `get_db_session()`

FastAPI `Depends()` declares that a route needs a dependency. In Phase 3.4, the
mounted internal meeting routes use this flow:

```
Route
  → Depends(get_meeting_service)
  → Depends(get_db_session)
  → request-scoped AsyncSession
  → MeetingService
  → Repository
  → SQLAlchemy
  → PostgreSQL
```

`get_db_session()` obtains a session from the shared factory and yields it to
the route dependency. `get_meeting_service()` uses that same session to build
`MeetingRepository`, `TranscriptRepository`, and `MeetingService`; after the
route/service completes, the dependency context closes the session. If an
exception propagates, the dependency rolls back. It does not auto-commit because
only the service knows whether the complete use case has succeeded; successful
writes are committed there.

Repositories deliberately do not own request/session lifecycle: they receive a
session, issue database work, and flush. If each repository created sessions or
committed independently, one use case could not reliably coordinate several
writes atomically. The meeting router is mounted for internal `POST /meetings`
and `GET /meetings/{meeting_id}`. Gateway `/api/v1` forwarding and
authentication remain future work.

An interviewer may ask, “Why does the dependency roll back but not commit?”
Answer: rollback is failure cleanup for the request boundary; commit is a
business/use-case decision owned by the service.

## Phase 3.4 — Internal Meeting API study section

### What was added and why it is internal

Phase 3.4 mounts two meeting-service endpoints: `POST /meetings` and
`GET /meetings/{meeting_id}`. They are internal service endpoints, not the
future public `/api/v1/meetings` gateway contract. Authentication, JWT identity,
gateway forwarding, and `MeetingServiceClient` are not implemented, so exposing
a final public boundary now would be premature. The internal route slice proves
the existing service architecture end-to-end without pretending ownership UUIDs
supplied in `MeetingCreate` are an authorization model.

### Reconstructing the router

**A. `APIRouter`** — `APIRouter(prefix="/meetings", tags=["meetings"])` groups
meeting endpoints. The prefix supplies the common internal path; tags organize
the service's OpenAPI output. `app.include_router(meetings_router)` in
`meeting-service/app/main.py` makes those routes active.

Endpoint decorators state the HTTP contract. `@router.post("")` uses the
router prefix, declares `response_model=MeetingPublic`, and explicitly returns
HTTP 201. `@router.get("/{meeting_id}")` binds the path parameter and returns
HTTP 200 by default. `response_model` asks FastAPI to validate/serialize the
returned DTO, preventing ORM entities from becoming the response contract.

**B. Service dependency** — `get_meeting_service` is a FastAPI dependency. Its
`session: AsyncSession = Depends(get_db_session)` parameter causes FastAPI to
resolve the request-scoped session first. It constructs `MeetingRepository` and
`TranscriptRepository` with that same session, then constructs `MeetingService`.
The route receives the ready-to-use service through
`Depends(get_meeting_service)` rather than repeating object construction in
every endpoint.

**C. POST route** — FastAPI validates the request body as `MeetingCreate`.
The thin route passes that DTO to `MeetingService.create_meeting()` and returns
the resulting `MeetingPublic`. The service, not the route, parses UUIDs, creates
the ORM entity, uses the repository, commits the successful write, and maps the
result back to a DTO.

**D. GET route** — FastAPI supplies `meeting_id` as a string path parameter.
The route passes it unchanged to `MeetingService.get_meeting()`. The service
parses/validates the UUID, looks it up through the repository, raises
`NotFoundError` when absent, and maps an entity to `MeetingPublic` when found.

**E. Error flow** — routes do not catch `AppError`. A missing meeting follows
`MeetingService → NotFoundError("Meeting not found.") → shared handler → 404
ErrorResponse`; an invalid UUID follows `MeetingService → ValidationError → 422`.
An unexpected exception reaches the centralized handler and becomes a safe 500.
The request-logging/exception infrastructure provides the request ID.

### Runtime flow and transaction ownership

```text
HTTP request
  ↓
FastAPI route
  ↓
Depends(get_meeting_service)
  ↓
Depends(get_db_session)
  ↓
request-scoped AsyncSession
  ↓
MeetingRepository + TranscriptRepository
  ↓
MeetingService
  ↓
repository method
  ↓
AsyncSession → PostgreSQL
```

`get_db_session` owns session lifetime and rolls back when an exception escapes.
It does not commit automatically. Repositories add/execute/flush but do not
commit. `MeetingService` commits only after successful write use cases. Routes
therefore must not create sessions, issue SQL, create ORM entities, parse UUIDs,
commit, roll back, invent business rules, or translate application errors.

An alternative would be to put SQL or `AsyncSession` work directly in each
route. That is shorter initially, but it duplicates behavior, couples HTTP to
persistence, makes route tests harder, and destroys the established transaction
boundary. The accepted trade-off is a small dependency function and explicit
service composition in exchange for predictable layering.

### Route tests: dependency override versus PostgreSQL

`test_meeting_routes.py` uses standard-library `unittest` and FastAPI
`TestClient`. In production FastAPI resolves:

```text
get_meeting_service → get_db_session → repositories → MeetingService
```

In a route test, `app.dependency_overrides[get_meeting_service]` injects a mock
service instead. `AsyncMock` simulates async `create_meeting`/`get_meeting`
calls; `MagicMock` holds the boundary object. `TestClient` makes synchronous
test calls while running the ASGI application, so the test still exercises
routing, Pydantic request validation, response serialization, exception
handlers, and request-ID behavior.

The five current route tests are:

- `test_meetings_router_is_mounted`
- `test_create_meeting_returns_created_dto_from_service`
- `test_get_meeting_returns_dto_from_service`
- `test_missing_meeting_uses_standard_not_found_response`
- `test_invalid_meeting_id_uses_standard_validation_response`

Mocking is appropriate here because the route's job is HTTP adaptation, not
database correctness. Repository/service unit tests and the opt-in PostgreSQL
integration test cover lower boundaries. The trade-off is that route mocks do
not prove actual SQL behavior; they keep feedback fast and deterministic.

### Interview-ready answers

**How does a request reach the database?** “FastAPI resolves the route's
`get_meeting_service` dependency, which first resolves `get_db_session`. That
request-scoped session builds both repositories and `MeetingService`. The route
calls the service, which uses a repository through the same session; SQLAlchemy
then reaches PostgreSQL. The service commits successful writes, while the
session dependency rolls back propagated failures.”

**Why use dependency injection?** “It creates request-scoped collaborators
consistently and lets tests replace the service boundary without a database.”

**Why not put SQL in routes?** “Routes should translate HTTP to use cases.
Keeping SQL in repositories and decisions/commits in services makes each layer
testable and keeps transaction ownership clear.”

**Why are internal and public paths different?** “`/meetings` is the current
internal service contract. `/api/v1/meetings` belongs to the gateway and waits
for gateway forwarding plus authentication.”

**Why are route tests mock-based?** “They verify the HTTP adapter and dependency
composition independently; a separate opt-in test covers real PostgreSQL.”

**How does FastAPI serialize `MeetingPublic`?** “The route declares it as
`response_model`, so FastAPI validates and serializes the DTO rather than
exposing an ORM entity.”

## Current model facts

`Meeting`: `id`, `organization_id`, `created_by`, `title`, `description`,
`scheduled_at`, `participants`, `status`, `created_at`, `updated_at`.
Ownership UUIDs are **not foreign keys** because corresponding models do not
yet exist. `Transcript`: `id`, `meeting_id`, `segments`, `language`,
`created_at`, `updated_at`. `meeting_id` is unique and references `meetings.id`
with `ON DELETE CASCADE`.

The ORM and Pydantic each own a `MeetingStatus`; both use the same lowercase
values but are converted by `.value`. Stored nullable transcript language is
currently normalized to `"en"` for the non-null DTO; this is not lossless and
is a deferred schema/model alignment decision.

## Interview practice

For every answer below, say what is implemented now and what remains planned.

### Level 1 — Basic understanding

| Question | Expected answer | Likely follow-up / what it tests |
|---|---|---|
| What does the project do? | It is a meeting-intelligence platform. Current work persists meetings/transcripts; summarization and public routes are not implemented yet. | Scope honesty; system understanding. |
| Why PostgreSQL? | We need transactions, constraints, relationships, JSONB, and deliberate migrations for business data. | Relational-data trade-offs. |
| What is an ORM / SQLAlchemy? | An ORM maps Python classes to tables; SQLAlchemy supplies the mapping and async database API. | Abstraction versus SQL knowledge. |
| What is Alembic / a migration? | Alembic records ordered schema changes. A migration makes the same schema reproducible across databases. | Safe schema evolution. |
| What is AsyncSession? | It is the async unit through which SQLAlchemy executes and tracks a transaction for a request/use case. | Async resource lifecycle. |
| What is JSONB? | PostgreSQL's binary JSON type; we use it for flexible participant and segment structures. | When normalization is preferable. |

### Level 2 — Implementation

| Question | Expected answer | Likely follow-up / what it tests |
|---|---|---|
| Explain Meeting and Transcript. | Meeting owns metadata and status. Transcript has one unique `meeting_id`, JSONB segments, and optional language. | Model/schema reading. |
| Why UUIDs? | They are suitable across service boundaries and avoid exposing sequential IDs. | Trade-offs with index locality. |
| Why JSONB for participants? | The current shape is flexible and not queried relationally. | When to make a participant table. |
| Why a PostgreSQL enum? | It constrains persisted lifecycle values; ORM configuration persists lowercase values, matching the migration. | Names versus values. |
| Explain MeetingRepository. | It performs typed async data access: create/flush, get, organization list with ordered pagination, and status update/flush. | Why no commit. |
| Why `created_at DESC, id DESC`? | It makes page ordering deterministic when timestamps tie. | Pagination correctness. |
| Explain `create_meeting`. | It converts DTO IDs to UUIDs, creates a pending ORM entity, flushes through the repository, commits once, then maps a public DTO. | Mapping and transactions. |
| Why parse UUIDs in the service? | The service owns the API/domain-to-persistence boundary and turns invalid input into `ValidationError`. | Boundary responsibility. |

### Level 3 — Architecture

| Question | Expected answer | Likely follow-up / what it tests |
|---|---|---|
| Why a service layer? | It coordinates business decisions, mappings, errors, and transaction completion without coupling to FastAPI. | Separation of concerns. |
| Why do repositories not commit? | One use case may require several writes atomically; only the service knows the complete boundary. | Atomicity. |
| Where is rollback? | `get_db_session()` rolls back when an exception propagates; services do not duplicate that responsibility. | Failure handling. |
| Why separate DTOs and ORM? | API contracts should not be persistence objects; explicit mapping protects the boundary. | `from_attributes` trade-offs. |
| Why two status enums? | Separate layer ownership; explicit `.value` conversion keeps them safely aligned today. | Future consolidation. |
| Why aren't owner IDs foreign keys? | User/organization tables are not modeled; we retain typed ownership UUIDs without claiming nonexistent relations. | Incremental schema design. |
| Why no ON CONFLICT? | Create and replace have intentionally distinct domain behavior. | Semantics before convenience. |

### Level 4 — Failure and debugging

| Question | Expected answer | Likely follow-up / what it tests |
|---|---|---|
| What if flush fails? | It raises; no commit occurs, and the session dependency rolls back as the exception propagates. | Transaction lifecycle. |
| What if commit fails? | The exception propagates to the dependency/handler path; we do not report success. | Durability reasoning. |
| What if PostgreSQL goes down? | Database operations fail and readiness detects connectivity; unexpected persistence errors are not exposed raw to clients. | Resilience boundaries. |
| What if a transcript is created twice? | The service detects the existing transcript and raises `ConflictError`; uniqueness also exists in the database. | Application versus database enforcement. |
| What if a meeting is missing or ID is invalid? | Missing is `NotFoundError`; malformed UUID is `ValidationError`. | Precise errors. |
| What if language is NULL? | The current DTO mapping returns `"en"`; it is valid but not lossless, and documented as deferred. | Honest limitations. |
| How did you debug the Alembic issue? | I inspected config/migration/state, shortened the ID to fit default Alembic storage, then checked head/history/applied schema. | Evidence-based debugging. |
| Why not install pytest? | Existing tests use standard `unittest`; adding a tool was unnecessary and outside the repository convention. | Restraint and conventions. |

### Level 5 — Deep follow-up

| Question | Expected answer | Likely follow-up / what it tests |
|---|---|---|
| Can two requests both create a transcript? | The pre-check can race; the unique database index is the final invariant. A production route should translate a unique-violation race to `ConflictError`. | Concurrency limits. |
| Is application duplicate checking enough? | No. It improves domain messaging but the unique constraint is required for correctness under concurrency. | Defense in depth. |
| What if response creation fails after commit? | Data may be durable even though the client sees failure; retries need idempotency design when API routes are introduced. | Distributed failure modes. |
| Would you introduce Unit of Work? | Only when multiple use cases/resources make explicit transaction composition clearer than the current injected session. | Avoiding premature abstractions. |
| When would ON CONFLICT fit? | When the business contract deliberately defines idempotent/upsert semantics, not merely to reduce code. | Domain-led design. |
| How model organizations/users? | Add models, migrations, foreign keys, indexes, authorization semantics, and a data migration plan. | Incremental relational modeling. |
| How enforce status transitions? | Define a real transition graph in the service and test it; current code intentionally permits any valid status. | Not inventing requirements. |
| How support atomic meeting+transcript writes? | Share the same injected session and commit once after both repositories flush. | Transaction composition. |
| How handle distributed transactions? | Avoid assuming a database transaction spans services; use idempotency, outbox/sagas, and compensations as requirements dictate. | Distributed systems judgment. |
| How add optimistic concurrency? | Add a version column/conditional update and define conflict behavior in a migration and service contract. | Concurrent update control. |

## Explain this project yourself

- [ ] Explain the product and the implemented versus planned boundary.
- [ ] Draw Route → Service → Repository → AsyncSession → PostgreSQL.
- [ ] Explain Meeting, Transcript, UUID, JSONB, native enum, and cascade deletion.
- [ ] Explain Alembic revision `0001_meetings_transcripts`, upgrade, and downgrade.
- [ ] Explain async session injection, flush versus commit, rollback, and transaction ownership.
- [ ] Explain DTO versus ORM, UUID/enum conversion, pagination, and deterministic ordering.
- [ ] Explain transcript create versus replace and current error behavior.
- [ ] Name the deferred language-nullability, duplicate-enum, owner-FK, routes, and status-rule decisions.
- [ ] Tell the six real engineering stories in `problems-and-solutions.md`.
- [ ] Describe a future improvement without claiming it is already implemented.
