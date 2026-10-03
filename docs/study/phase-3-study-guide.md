# Phase 3 Study and Interview Guide

## Current elevator pitch

MannerAI is a microservice-oriented meeting-intelligence platform. Through
Phase 9, it includes authenticated Gateway and Meeting Service persistence,
the typed AI processing path, a Phase 8 executor, and Phase 9 Redis/Celery
transport with dedicated signed worker authorization and a PostgreSQL-backed
job lifecycle. PostgreSQL persistence, concurrent claims, lease reclamation,
stale-token fencing, and terminal results were validated against PostgreSQL.
Live Redis/Celery execution was not validated because Redis was unavailable.
Phase 10 — Vector Search & RAG is next; Docker remains deferred. Earlier
sections below remain study notes for their named phase/checkpoint.

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
| Alembic migrations | At the Phase 3 checkpoint, revision `0001_meetings_transcripts` created the then-current domain schema and reversed it in dependency order. The current head is `0004_meeting_domain_results`. | Creating tables at app startup is unsafe and untraceable. | Add reviewed migrations per intentional schema change. |
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

> Historical checkpoint: this section describes the Phase 3.4 implementation
> boundary. Phase 4 authentication, Gateway forwarding, and ownership are
> covered in the Phase 4 section below.

### What was added and why it is internal

Phase 3.4 mounts two meeting-service endpoints: `POST /meetings` and
`GET /meetings/{meeting_id}`. They are internal service endpoints, not the
public `/api/v1/meetings` Gateway contract. At this historical checkpoint,
authentication, JWT identity, Gateway forwarding, and `MeetingServiceClient`
were not implemented. Phase 4 later added that public boundary and enforces
ownership using the authenticated identity; the original internal route alone
did not treat request ownership UUIDs as authorization.

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
Ownership UUIDs are **not foreign keys**. A `User` model now exists, but the
initial meeting migration did not create a foreign key for `created_by`; no
organization model exists for `organization_id`. `Transcript`: `id`, `meeting_id`, `segments`, `language`,
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
| What does the project do? | It is a meeting-intelligence platform. The implemented system includes authenticated Gateway-to-Meeting persistence flows and a Phase 7 AI application boundary with five typed agents, OpenAI adapter, validation, and domain mapping. Public processing, automatic persistence, and production pipeline integration remain deferred. | Scope honesty; system understanding. |
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
| Why aren't owner IDs foreign keys? | `created_by` is checked against the authenticated user but the initial meeting schema has no FK; organization membership/schema is not implemented. | Incremental schema design. |
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

---

## Phase 4 — Security and authentication study section

### Trust and token model

| Topic | Project explanation | Interview follow-up |
|---|---|---|
| Authentication vs authorization | Authentication establishes the user UUID from a validated access JWT; authorization checks whether that identity owns the requested meeting. | Can a valid user access every record? No. |
| Access JWT vs refresh token | Access JWT is signed, short-lived, and carries `sub`, `type=access`, `iat`, `exp`. The opaque refresh token identifies a persisted, revocable session. | Why not use one long-lived JWT? It would be harder to revoke or rotate. |
| Refresh token hashing | Tokens are generated with `secrets`, then only SHA-256(token) is stored. High entropy makes offline guessing impractical; the stored digest itself is not accepted as the token. | Why not use the password hash function? A random token does not need a deliberately slow password hash. |
| Rotation and replay | A successful refresh revokes the old session and creates a replacement in one transaction. Reusing the old token fails once its revoked state is committed. | What is not yet proven? The PostgreSQL replay/concurrency test has not run against the current schema. |
| `SELECT FOR UPDATE` | PostgreSQL locks the session row while the service validates and rotates it, serializing attempts using the same token. | Why is a mock insufficient? It cannot prove database lock behavior or isolation semantics. |
| Password hashing vs encryption | Passwords are one-way hashed with Passlib `pbkdf2_sha256`; they are never stored as reversible ciphertext or plaintext. | Why not encrypt passwords? Authentication needs verification, not recovery of the original value. |
| HS256 vs RS256 | Gateway access JWTs use configured HS256. Gateway-to-Meeting identity uses RS256 so Gateway holds the private signing key while Meeting holds only the public verification key. | Why separate the keys? Meeting must verify identity without gaining the ability to mint it. |
| Internal principal | Gateway resolves the external user first, then signs `sub`, `type`, `iss`, `aud`, `iat`, and `exp`. Meeting verifies signature and required claims. | Why not trust `X-User-ID`? A client can forge an ordinary header. |
| Ownership | Meeting stores the authenticated subject as `created_by` and verifies it on individual meeting and transcript operations. Owner succeeds; non-owner is forbidden. | Can request payload choose the owner? No; ownership comes from the verified principal. |
| Service/repository transactions | Repositories query/add/update/flush; application services coordinate writes and commit the use case. `get_db_session()` rolls back escaping exceptions. | Why not commit in each repository? A multi-repository use case needs one transaction boundary. |

### Security test strategy and evidence

Normal focused security coverage reported **50 tests run: 44 passed, 6 skipped**.
The full backend suite reported **209 run: 202 passed, 7 skipped**. The skipped
tests are opt-in PostgreSQL integration tests guarded by
`RUN_POSTGRES_INTEGRATION=1`.

| Category | Normal test evidence | PostgreSQL evidence |
|---|---|---|
| Password hashing | Hashing, valid/invalid password, malformed hash, generic unknown-user failure | Not needed for ordinary password unit behavior |
| Access JWT | Valid, expired, malformed, bad signature, wrong type, invalid subject, missing credentials | Not required for token-claim unit cases |
| Refresh validation and rotation | Service tests cover storage hash, generated token properties, successful rotation, revoked/expired/unknown/missing-user rejection | Added login persistence and old-token replay tests; skipped pending schema |
| Logout | Service tests cover valid revocation and generic unknown/repeated behavior | Added real session revocation test; skipped |
| Multi-session | No executed database-backed evidence | Added independent-session test; skipped |
| Concurrency | Implementation uses PostgreSQL `FOR UPDATE`; not integration-proven | Concurrent same-token test added; skipped |
| Rollback | Session dependency rollback is mock-tested | Rotation rollback test added; skipped |
| Current user | Route/dependency tests cover authentication, safe profile, identity and sensitive-field restrictions | No database integration claim |
| Meeting ownership | Service/route tests cover owner and non-owner meeting/transcript actions | No ownership integration claim |
| Internal principal | Tests cover signature, expiry, type, issuer, audience, subject, signer separation, and external JWT rejection | Unit/crypto tests |

The configured PostgreSQL instance was reachable, but its Alembic revision was
`0001_meetings_transcripts` and it lacked the Phase 4 `users` and
`refresh_sessions` tables. Migrations were not run. Thus lifecycle persistence,
second use of a rotated token, multi-session independence, concurrency, and
rotation rollback still need execution against the current schema.

### Interview practice

- How does a password hash differ from a refresh-token hash? Passwords are low-entropy human secrets and use PBKDF2; refresh tokens are high-entropy random values and use fast SHA-256 for indexed lookup.
- Why use an internal principal instead of forwarding the external JWT? It gives Meeting a short-lived, audience-specific assertion and keeps external JWT trust and the private key at Gateway.
- What does row locking guarantee? Under PostgreSQL, requests rotating the same session serialize around that row. The implementation is present, but the opt-in concurrent integration test still needs to run against the current schema.
- What is an authentication test matrix? It checks success and failure boundaries—malformed, expired, wrongly signed, wrong-type, unauthorized, cross-user, and replay cases—rather than only happy paths.
- What is the current membership limitation? Individual meeting operations enforce `created_by`; organization-wide internal listing still lacks membership authorization and is not exposed as a Gateway list route.

## Phase 5 — Meeting domain and persistence study section

### Architecture and persistence concepts

| Topic | Project implementation | Interview follow-up |
|------|-------------------------|---------------------|
| ORM model vs Pydantic schema | ORM classes define PostgreSQL columns, constraints, and relationships; Pydantic schemas validate request data and serialize DTOs. Services map explicitly between them. | Why not return ORM entities from FastAPI? Keep persistence state separate from the client contract. |
| Repository vs service | Repositories use `AsyncSession.execute(select(...))`, add rows, flush, and return ORM objects. Services enforce ownership, coordinate use cases, map DTOs, and commit. | Where does a duplicate-version conflict become a domain error? In SummaryService. |
| `flush()` vs `commit()` | `flush()` sends pending SQL and surfaces generated values/constraints inside the transaction. `commit()` finalizes the successful service use case. | Why not commit in each repository? A service may coordinate multiple writes in one transaction. |
| Async query and loading | Repositories use async `execute()` and explicit scalar lookups/lists. Services map scalar columns and do not traverse relationships to build DTOs, avoiding implicit lazy I/O and relationship N+1 queries. | How do you avoid an async lazy-load during response serialization? Build DTOs from explicitly loaded scalar data. |
| Ordering and pagination | Lists order deterministically: summaries by version then ID; tasks/follow-ups by `created_at DESC, id DESC`; decisions by `created_at ASC, id ASC`. API lists use shared pagination schemas. | Why include a unique tie-breaker? Stable pages when timestamps match. |
| Relationships and delete behavior | Meeting has one optional Transcript and many Summary/Task/Decision/FollowUp rows. Meeting child FKs cascade. Task has an optional User assignee; deleting the User sets `assignee_id` to `NULL`. | Why preserve a Task when its assignee disappears? The action item remains useful without an assignee. |
| Summary versions | Database requires positive version and unique `(meeting_id, version)`. Latest lookup selects the highest version. Service accepts explicit versions; the current HTTP create route only sends the default version 1. | Is version auto-incremented? No. |
| Partial updates | `TaskUpdate` and `FollowupUpdate` apply only supplied fields; meeting association is immutable. | How does `exclude_unset=True` differ from writing default values? It preserves fields omitted by the caller. |
| Ownership | Gateway signs a short-lived internal principal; result services resolve the result's Meeting and check its owner. Nested routes also check parent/result consistency. | Can a client supply `created_by`? No; ownership comes from authenticated identity. |

### Migration and PostgreSQL evidence

The linear migration chain is `0001_meetings_transcripts → 0002_users →
0003_refresh_sessions → 0004_meeting_domain_results`. The verified local
development database moved from `0001` to `0004`; `alembic check` reported no
pending operations. PostgreSQL tests verified result persistence, Summary
uniqueness/latest ordering, Task/FollowUp status filtering, `ON DELETE SET
NULL`, and Meeting-child cascades.

The PostgreSQL test found that SQLAlchemy/asyncpg wraps the uniqueness error so
the constraint name was not available where SummaryService first looked.
The service now checks wrapped exception causes/diagnostics and maps the named
Summary constraint to `ConflictError`. This is why a mocked unit test alone was
not sufficient: the real driver exception shape mattered.

### Phase 5 test evidence

- Focused Phase 5/API and Meeting/Transcript route tests: **86 passed**.
- Security regression suite: **140 passed**.
- Opt-in PostgreSQL integration tests: **7 passed**.
- Full backend suite with `RUN_POSTGRES_INTEGRATION=1`: **259 passed**.

### Phase 5 design boundaries

- Public organization-wide Meeting listing remains deferred: no persisted
  Organization/membership model or membership authorization policy exists.
  A client-supplied `organization_id` alone is not authorization.
- No Meeting search fields or client-selected sort keys are defined; the
  internal list retains deterministic `created_at DESC, id DESC` ordering.
- At the Phase 5 checkpoint, MeetingInsight was deferred because row shape,
  cardinality, and lifecycle/version semantics were not decided. Phase 7 later
  defined its immutable snapshot shape; version/replacement policy remains
  deferred.
- At the Phase 5 checkpoint, Phase 6 had not started. Phase 6 is now complete;
  its AI Service foundation and current deferred boundaries are documented
  below. Workers, embeddings, vector search, and frontend integration remain
  outside the Phase 6 foundation.

## Phase 6 — AI Service foundation study section (historical checkpoint)

### Architecture and boundaries

The AI Service lives in `backend/ai-service/` and is independent of Meeting
Service persistence. Its `ModelProvider` protocol isolates agents from vendor
SDKs. The common `Agent` accepts `AgentInput`, builds a provider-neutral
`ModelRequest`, and sends provider output through shared Pydantic structured
validation. At the Phase 6 checkpoint no concrete provider client was
implemented; Phase 7 added the OpenAI adapter.

`ProcessingRequest` selects operations and carries the meeting/transcript IDs
and optional context. `AIProcessingOrchestrator` explicitly maps each
operation to one of five agents and executes sequentially in request order.
`ProcessingResult` contains ordered typed `OperationResult` values and retains
the caller's application-controlled IDs separately from model output. Its
aggregate status is `completed`, `partially_failed`, or
`failed`; one operation's failure does not erase successful outputs. Duplicate
operations are deduplicated in the request while preserving their first
occurrence, and the result contract independently enforces uniqueness.

| Agent | What it returns | Boundary |
|-------|-----------------|----------|
| `SummaryAgent` | `content`, `key_topics` | No persistence identifiers |
| `TaskAgent` | A possibly empty list of task candidates with title, optional description, transcript-level assignee name, and explicit calendar date | Does not resolve user IDs or lifecycle status |
| `DecisionAgent` | Decision statement, optional context, participant names | Separates reached decisions from proposals or unresolved discussion |
| `FollowUpAgent` | Subject, `body_html`, transcript-level recipient name and/or validated email | Does not send, schedule, persist, or resolve recipient IDs |
| `InsightAgent` | Controlled category, title, description | At the Phase 6 checkpoint no MeetingInsight persistence contract existed; Phase 7 added the domain/ORM snapshot contract. |

AI output models are not ORM models or Meeting Service persistence schemas.
Future application work must explicitly map validated candidate output to a
domain use case before persistence. The AI Service does not access SQLAlchemy,
repositories, database sessions, or user resolution.

### Transcript source-data boundary

Agents receive transcript content from their caller. They serialize selected
transcript fields as deterministic JSON, preserving segment order and available
speaker, timing, and language data. Prompts identify transcript content as
untrusted source material rather than instructions and direct the model to use
supported facts, avoid invented names/deadlines/recipients/decisions, and
preserve uncertainty. Pydantic validates structure and types; it cannot prove
that an output is semantically grounded. Prompt instructions do not guarantee
complete prevention of prompt injection or hallucination.

### Phase 6 hardening and verification

Block 5 found that `ProcessingRequest` rejected duplicate operation execution
by deduplicating its list, while a directly constructed `ProcessingResult`
could still contain duplicate operations and outcomes. The result contract now
rejects duplicate requested operations; `test_ai_orchestration.py` covers the
regression.

Final Phase 6 validation used the project `.venv`: AI tests **91 passed**;
relevant Meeting/domain/Gateway/database regressions **68 run, 1 skipped**;
full backend **350 run, 8 skipped**. The opt-in PostgreSQL integration modules
had **7 skipped** because `RUN_POSTGRES_INTEGRATION` was unset. These skips are
not PostgreSQL integration passes. `pip check` reported no broken requirements
and `git diff --check` passed.

### Deferred after the Phase 6 checkpoint (historical)

- Concrete provider adapter, AI-to-domain mapping, and MeetingInsight schema
  were deferred at this checkpoint and added in Phase 7.
- Production pipeline and Gateway integration.
- Background processing, Redis/Celery, semantic search, and frontend
  integration.
- Docker/infrastructure work and later roadmap phases.

## Phase 7 — AI Meeting Intelligence Integration study section

### Application flow and ownership

```text
ProcessingRequest + caller-loaded TranscriptInDB
  → transcript normalization → AgentInput
  → AIProcessingService → AIProcessingOrchestrator
  → five agents → injected ModelProvider
  → structured JSON/Pydantic validation → typed AI outputs
  → explicit domain mapping → domain-ready input DTOs
  → caller-owned persistence decision
```

`AIProcessingService` checks transcript, meeting, and orchestrator result
identities; preserves requested-operation order; maps each successful output;
and returns safe operation-level outcomes. It does not retrieve the transcript,
create an `AsyncSession`, call a repository, or commit. A future application
caller must explicitly choose whether to pass domain-ready inputs to Meeting
Service persistence.

### Engineering decisions to explain

| Decision | Project-specific reason | Interview explanation |
|----------|-------------------------|-----------------------|
| `ModelProvider` abstraction | Agents depend on `ModelRequest`/`ModelResponse`, not OpenAI SDK types. OpenAI is an injected adapter; the tests inject a deterministic test-only provider. | Provider selection, credentials, SDK behavior, and provider failures stay outside agent contracts. The integration suite needs no credentials or network. |
| Agents do not access PostgreSQL | Agents receive `AgentInput` built from the caller's transcript and optional context. | This keeps model execution independently testable and prevents an agent from bypassing Meeting Service ownership, authorization, and transaction rules. |
| Model output excludes persistence IDs | AI output schemas contain candidate content, not `meeting_id`, row UUIDs, timestamps, or ORM state. | The application—not generated text—owns resource identity and persistence lifecycle. |
| Trusted identity comes from the application | `ProcessingRequest` and `TranscriptInDB` carry meeting/transcript IDs; normalization, orchestrator, and service verify that they agree. Mappers use the trusted request meeting ID. | Model-generated identity is never accepted as authority. |
| Mapping is separate from generation | Typed agent outputs map through explicit functions into existing `SummaryBase`, `TaskBase`, `DecisionBase`, `FollowupBase`, and `MeetingInsightBase` contracts. | Provider schemas and persistence/domain contracts evolve for different reasons; mapping reports when safe representation is impossible. |
| MeetingInsight is relational | Insights need meeting-scoped storage, controlled categories, foreign-key ownership, deterministic listing, and Meeting deletion behavior. | It is a first-class candidate snapshot, not a vector-search record or an unstructured field on the summary. |
| No semantic deduplication yet | No run/replacement policy or uniqueness definition exists; same-looking candidates can have different meaning over time. | Retain candidates until a product policy defines identity, confidence, and replacement semantics. |
| No automatic commit | AIProcessingService has no persistence dependency and returns DTOs only. | The caller owns domain-service invocation and transaction policy; model generation must not silently write rows. |

### Typed results, failures, and limitations

The orchestrator runs requested operations sequentially in request order.
Duplicate operations are removed at request construction while preserving
first occurrence. Each operation is completed with a typed output or failed
with a sanitized code/message. The aggregate status is `completed` if all
succeed, `partially_failed` if some succeed, and `failed` if none succeed.
Mapping failures affect only their operation, preserving other successes.

- Task candidates may include calendar dates, but Task persistence currently
  accepts `datetime` for `due_at`; the mapper refuses to guess time/timezone.
  An `assignee_name` is not converted into a User UUID.
- Follow-up recipient names without email addresses cannot map to the current
  email-only domain contract; no address is inferred.
- `InsightCategory` is a controlled enum, but typed validation cannot prove
  semantic grounding. Prompts and schemas reduce risk without guaranteeing
  truthfulness.
- MeetingInsight is an immutable snapshot (`id`, `meeting_id`, `category`,
  `title`, `description`, `created_at`) with no update/status/version/run ID or
  provider metadata. Similar insights may coexist; no semantic deduplication
  or replacement exists.
- At the Phase 7 checkpoint, migration `0005_meeting_insights` was defined but
  unapplied and not PostgreSQL-validated. It is now included in the current
  database schema at Alembic head `0006_processing_jobs`.

### What Phase 7.6 integration tests prove

The test-only provider supplies predetermined JSON and can simulate provider
failure or malformed output. Tests run the real
`AIProcessingService → AIProcessingOrchestrator → agents → structured-output
validation → domain mapping` path. They cover all five operations, empty
collections, partial failures, malformed output, ordering/deduplication,
transcript ordering/speakers/timestamps/language, trusted identity, unsafe
mapping, and absence of persistence imports/side effects. They do not validate
live OpenAI behavior, semantic accuracy, retries, or background execution.
Migration 0005 was not validated during the Phase 7 checkpoint; the later
Phase 9 PostgreSQL database is now at head 0006.

Phase 7 checkpoint verification: **422 backend tests run, 8 skipped; all
non-skipped tests passed**;
AI suite **153 passed**; `pip check` and `git diff --check` were clean. The
skips are not evidence that migration 0005 or MeetingInsight persistence was
tested against PostgreSQL.

### Deferred after Phase 7

Public AI processing/job APIs, Gateway/production pipeline integration,
automatic persistence invocation, background workers/retries/idempotency,
applying and PostgreSQL-validating migration 0005, insight deduplication,
Qdrant/RAG/search, frontend AI workflow, Gmail, and deployment remain future
work.

## Phase 9 — Redis, Celery, and durable job lifecycle

### Why Redis and Celery

AI work should not hold an HTTP request open while providers and multiple
agents run. Celery provides task delivery and worker orchestration; Redis is
the configured broker. The queue boundary is implemented, while live
Redis/Celery worker execution was not validated because Redis was unavailable
in the development environment. Do not describe broker integration as live
tested based on unit or mocked-publisher tests.

### Queue data is not trusted identity

The task message uses a strict primitive envelope containing the job,
meeting, transcript, and requested operation identifiers. It excludes
`TrustedExecutionContext`, a freely supplied `user_id`, access/refresh tokens,
ORM/session objects, credentials, and AI results. The worker must not turn an
arbitrary queue field into authority. It verifies the producer authorization
and exact envelope bindings, then reconstructs trusted context from the
verified subject.

### Producer-signed background authorization

The producer signs a short-lived, purpose-specific RS256 authorization with a
dedicated private key. It binds issuer, audience, purpose, subject, time
window, `jti`, and the exact job/meeting/transcript/operation values. The
worker verifies signature, issuer, audience, lifetime, purpose, and all
bindings before it creates a trusted execution context or proceeds to the
existing executor/Meeting Service ownership checks.

This credential is not an external user access JWT and is not the
Gateway-to-Meeting internal principal. Those tokens have different audiences,
purposes, and trust flows. Dedicated background signing and verification
keys keep those boundaries separate. A `jti` is unique metadata here; without
a durable JTI ledger, it does not provide one-time replay prevention.

### PostgreSQL claims, leases, and fencing

The `processing_jobs` row is the durable application record; PostgreSQL is
not interchangeable with Celery task state. `SELECT FOR UPDATE` serializes
claims against the same row. A successful claim increments the persisted
attempt count and installs a random lease token and expiry. If a running
lease expires, another claim can reclaim the row as a new attempt with a new
token. Completion/failure methods check that token, so a stale worker cannot
overwrite the new attempt.

Phase 9.4's opt-in PostgreSQL integration passed **2/2 with no skips**. It
exercised persisted queue/claim state, concurrent claims, expired-lease
reclamation, attempt and lease replacement, stale completion/failure
rejection, and final terminal-state persistence. The lifecycle suite passed
**11/11**. These checks validate PostgreSQL behavior; they do not validate
live Redis delivery.

### Retry, delivery, and recovery limits

Celery retry scheduling and the application's persisted attempt count serve
different roles. PostgreSQL owns the allowed attempt count, due time, lease,
and terminal outcome. Transient infrastructure failures may be retried with
bounded backoff; validation, security, and application processing failures
are terminal under the current policy. Partial operation results are
persisted rather than retrying all successful operations.

Late acknowledgements and worker-loss redelivery improve recovery, and
PostgreSQL row locks/lease tokens protect state transitions. The system is
still at-least-once: it does not promise exactly-once execution or make
arbitrary provider/downstream side effects idempotent. If PostgreSQL is
unavailable before a claim or Celery cannot schedule a persisted retry,
operational redrive may be needed. There is no separate durable JTI replay
ledger or public job-status API.

Celery has no result backend configured. That is deliberate: task delivery
state is not the application's business lifecycle, which is persisted in
PostgreSQL. The AI executor continues to return typed results, and the job
row stores mapped results and sanitized failure details.

### Current Phase 9 checkpoint and next work

Migration `0006_processing_jobs` is applied at Alembic head. PostgreSQL
persistence, row locking, lease reclamation, stale-token fencing, and
terminal persistence are validated against PostgreSQL. Live Redis/Celery
execution remains unvalidated until a Redis-compatible broker is available.
Docker and Compose changes remain deferred. Phase 9 is complete; Phase 10 —
Vector Search & RAG is next.
