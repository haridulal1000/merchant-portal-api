# Merchant Portal API — Technical Overview

This document is the single source of truth for the backend codebase. Any AI or human reading it should be able to understand the architecture, conventions, and business rules without opening a single source file.

---

## 1. Purpose

A REST API for a merchant payments portal. Manages users, merchant applications, and risk review decisions across three user roles (SALES, REVIEWER, ADMIN). Built with FastAPI + SQLAlchemy 2.0 + PostgreSQL.

---

## 2. Demo notice

This is a **demonstration build**, not a hardened production deployment. Several mechanisms a production release would require are deliberately simplified:

- **Signup is open** — anyone can create an account with any role, including ADMIN. In production, signup would be invite-only, admin-gated, or restricted to a lower-privilege default role.
- **JWT secrets are committed as defaults** in `docker-compose.yml`. Production deployments must inject strong, per-environment secrets.
- **No rate limiting** on `/auth/login`, `/auth/signup`, or `/auth/refresh`. A brute-force protection layer belongs at the API gateway or as middleware.
- **No token family revocation.** Logout deletes the refresh token row, but stolen refresh tokens that were issued before the deletion remain valid until expiry. Production should revoke the entire family on password change or logout.
- **No audit log** beyond the `reviews` table. Login attempts, admin actions, and application edits are not recorded.
- **No email verification** on signup.
- **HTTP in dev** — production must terminate TLS at a reverse proxy and set `Secure` on cookies.

Everything else — authentication, RBAC, workflow rules, pagination, validation — is implemented to production standards.

---

## 3. Tech Stack

- **Framework:** FastAPI 0.115
- **ORM:** SQLAlchemy 2.0 (typed, declarative)
- **Database:** PostgreSQL 16
- **Validation:** Pydantic v2
- **Auth:** PyJWT + bcrypt
- **Server:** Uvicorn
- **Container:** Docker + Docker Compose

---

## 4. Architecture

### Folder layout

```
app/
  __init__.py
  config.py         Settings loaded from env (pydantic-settings)
  database.py       SQLAlchemy engine, session, Base
  models.py         ORM models and enums
  schemas.py        Pydantic request/response models
  security.py       bcrypt hashing, JWT encode/decode
  deps.py           Auth dependencies and role guards
  seed.py           Default 3-user seeder (idempotent)
  seed_demo.py      Demo data seeder (120 applications + reviews)
  main.py           FastAPI app, CORS, router registration
  routers/
    __init__.py
    auth.py         /api/auth/*
    users.py        /api/users
    applications.py /api/applications/*
    reviews.py      /api/applications/{id}/reviews
```

### Layer responsibilities

- **`config.py`** — Environment-driven settings. Single source of truth for secrets, DB URL, JWT expiry, CORS origins.
- **`database.py`** — Engine + session factory. Exposes `Base` for models and `get_db` as a FastAPI dependency.
- **`models.py`** — ORM tables and enums. No business logic here.
- **`schemas.py`** — Pydantic models for request validation and response serialization. Never exposes ORM internals.
- **`security.py`** — Password hashing (`bcrypt`) and JWT signing/verification. Pure functions, no DB access.
- **`deps.py`** — Auth dependencies: `get_current_user` and `require_roles(...)`. Used across routers.
- **`routers/*`** — HTTP layer. Each router handles one resource. Business rules live here and in small helper functions in the same file.
- **`main.py`** — App factory, CORS setup, global exception handling, route registration.

### Conventions

- **Routers are thin.** Business logic lives in the router function itself or in small pure helpers within the same file. No separate service layer for a project of this size.
- **Dependencies for auth.** Every protected route uses `Depends(get_current_user)` or `Depends(require_roles(...))`.
- **Row-level checks in the router.** SALES-visibility is enforced by query filters or explicit `if` checks, not by magic. If a rule is easy to miss, it is easy to grep.
- **Enums everywhere.** Status, roles, and decisions are Python `enum.Enum` classes backed by Postgres enums. No stringly-typed values.
- **Schemas, not dicts.** Every response is a Pydantic model. Every request body is a Pydantic model. No `dict` return types.
- **Transactions via `db.commit()`** at the end of each write handler. FastAPI's `get_db` closes the session in a `finally`.

---

## 5. Domain Model

### Users

```
id            string (uuid)   PK
email         string          unique, indexed
password_hash string          bcrypt
name          string
role          enum            SALES | REVIEWER | ADMIN
created_at    timestamptz
updated_at    timestamptz
```

### Merchant Applications

```
id              string (uuid)   PK
merchant_name   string
business_type   string
annual_revenue  float
contact_email   string
contact_phone   string
status          enum            DRAFT | SUBMITTED | UNDER_REVIEW | APPROVED | REJECTED
risk_score      float  NULL
risk_decision   enum   NULL     LOW | MEDIUM | HIGH | REJECTED
submitted_at    timestamptz NULL
sales_rep_id    string          FK -> users.id, indexed
created_at      timestamptz
updated_at      timestamptz     indexed (implicit via updated_at ordering)
```

### Reviews

```
id              string (uuid)   PK
application_id  string          FK -> merchant_applications.id, ON DELETE CASCADE, indexed
reviewer_id     string          FK -> users.id, indexed
action          enum            APPROVE | REJECT | UNDER_REVIEW
decision        enum            LOW | MEDIUM | HIGH | REJECTED
comment         string  NULL
created_at      timestamptz
```

### Refresh Tokens

```
id          string (uuid)   PK
token       string (512)    unique, indexed
user_id     string          FK -> users.id, ON DELETE CASCADE, indexed
expires_at  timestamptz
created_at  timestamptz
```

### Indexes

- `users.email` (unique)
- `merchant_applications.sales_rep_id`
- `merchant_applications.status`
- `reviews.application_id`
- `reviews.reviewer_id`
- `refresh_tokens.token` (unique)
- `refresh_tokens.user_id`

---

## 6. Authentication

### Token model

- **Access token:** JWT, 15-minute expiry, signed with `JWT_ACCESS_SECRET`. Contains `{ sub, email, role, type: "access", iat, exp }`.
- **Refresh token:** JWT, 7-day expiry, signed with `JWT_REFRESH_SECRET`. Contains `{ sub, email, role, type: "refresh", iat, exp }`.
- **Storage:** Refresh tokens are stored in the `refresh_tokens` table. Each row is single-use.
- **Rotation:** Every `/auth/refresh` call deletes the old refresh token row and issues a new pair. Reusing a consumed refresh token fails with 401.

### Flow

```
1. Client POSTs /auth/login with { email, password }
2. Server verifies bcrypt hash
3. Server signs an access token + a refresh token
4. Server persists the refresh token
5. Client stores both (production: access in memory, refresh in HttpOnly cookie)
6. Client sends `Authorization: Bearer <access>` on protected requests
7. On 401, client POSTs /auth/refresh with the refresh token
8. Server validates the refresh token is in the DB and not expired
9. Server deletes the old row and issues a new pair
10. Client retries the original request with the new access token
```

### Dependencies

- `get_current_user` — decodes the bearer token, validates `type == "access"`, loads the user from the DB. Raises 401 on any failure.
- `require_roles(*roles)` — factory returning a dependency that calls `get_current_user` and then checks `user.role` is in the allowed set. Raises 403 on mismatch.

---

## 7. Roles & Permissions

### SALES

- Create merchant applications (status starts at `DRAFT`)
- Edit their own `DRAFT` applications (PATCH)
- Submit their own `DRAFT` applications (`PATCH /submit`)
- List and view their own applications only
- View review history for their own applications
- Cannot record reviewer decisions (403)

### REVIEWER

- List and view all applications
- Record decisions on applications in `SUBMITTED` or `UNDER_REVIEW` status
- Cannot create or edit applications

### ADMIN

- Full access to all applications
- Can create applications on their own behalf
- Can edit applications in any status (bypasses the DRAFT-only restriction)
- Can record reviewer decisions
- Can list users via `/api/users`

### Enforcement

Two layers, always:

1. **Route dependency** — `require_roles(...)` on the endpoint.
2. **Row-level check** — SALES users are filtered to their own rows in list queries, and rejected on detail access to foreign rows with 403.

Tampering with a client-side role produces the wrong UI but the backend still rejects the action.

---

## 8. Workflow — Application Lifecycle

### Status transitions

| From | Trigger | To |
|---|---|---|
| — | SALES creates an application | DRAFT |
| DRAFT | SALES submits via wizard | SUBMITTED |
| SUBMITTED | REVIEWER action `APPROVE` | APPROVED |
| SUBMITTED | REVIEWER action `REJECT` | REJECTED |
| SUBMITTED | REVIEWER action `UNDER_REVIEW` | UNDER_REVIEW |
| UNDER_REVIEW | REVIEWER action `APPROVE` | APPROVED |
| UNDER_REVIEW | REVIEWER action `REJECT` | REJECTED |
| UNDER_REVIEW | REVIEWER action `UNDER_REVIEW` | UNDER_REVIEW (adds another audit row) |

Terminal states (`APPROVED`, `REJECTED`) reject further review actions with 400. Drafts cannot be reviewed — the reviewer's panel is only exposed for `SUBMITTED` and `UNDER_REVIEW` applications.

### Action vs decision

A review record has **two independent fields**:

- `action` — what happens to the application: `APPROVE`, `REJECT`, or `UNDER_REVIEW`. Drives the resulting status.
- `decision` — the reviewer's risk assessment: `LOW`, `MEDIUM`, `HIGH`, or `REJECTED`. Recorded for audit.

This separation means a HIGH-risk merchant can still be approved (with a comment), and a LOW-risk merchant can be rejected for a non-risk business reason. The action is intent; the decision is assessment.

### Side effects of `POST /applications/:id/reviews`

1. Insert a new row in `reviews`.
2. Update `merchant_applications.status` to the mapped status.
3. Update `merchant_applications.risk_decision` to the new decision.
4. Bump `updated_at`.

All four happen in one transaction. A failure rolls everything back.

---

## 9. API Reference

Base URL: `http://localhost:3000/api`

Interactive docs: `/docs`, `/redoc`, `/openapi.json`

### Health

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | Public | Liveness probe |

### Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/signup` | Public | Register a new user with a role |
| POST | `/auth/login` | Public | Authenticate, receive token pair |
| POST | `/auth/refresh` | Public | Exchange refresh token for a new pair (rotates) |
| GET | `/auth/me` | Bearer | Current authenticated user |

**POST /auth/signup**

```json
// Request
{ "email": "user@example.com", "password": "password123", "name": "Jane Doe", "role": "SALES" }

// Response 201
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "user": { "id": "...", "email": "...", "name": "...", "role": "SALES", "created_at": "..." }
}
```

Errors: 400 (email already registered), 422 (validation).

**POST /auth/login**

```json
// Request
{ "email": "sales@example.com", "password": "password123" }

// Response 200 — same shape as signup
```

Errors: 401 (invalid credentials).

**POST /auth/refresh**

```json
// Request
{ "refresh_token": "eyJ..." }

// Response 200 — new token pair (old refresh token invalidated)
```

Errors: 401 (invalid, expired, or already-consumed refresh token).

**GET /auth/me** — Response 200: `UserOut`.

### Users

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users` | ADMIN | Paginated user list, filter by `role` |

Query: `page` (≥1, default 1), `limit` (1–100, default 10), `role` (SALES|REVIEWER|ADMIN).

### Applications

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/applications` | Bearer | Paginated list, filtered by role |
| GET | `/applications/{id}` | Bearer | Single application |
| POST | `/applications` | SALES, ADMIN | Create a new DRAFT |
| PATCH | `/applications/{id}` | SALES, ADMIN | Update a DRAFT |
| PATCH | `/applications/{id}/submit` | SALES, ADMIN | DRAFT → SUBMITTED |

**GET /applications** query parameters:

- `page` — integer ≥ 1, default 1
- `limit` — integer 1–100, default 10
- `status` — one of `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`
- `search` — case-insensitive substring match on `merchant_name` or `contact_email`

**POST /applications**

```json
{
  "merchant_name": "Acme Widgets",
  "business_type": "Retail",
  "annual_revenue": 250000,
  "contact_email": "hello@acme.test",
  "contact_phone": "+15551234567"
}
```

**PATCH /applications/{id}** accepts any subset of the create fields. Only `DRAFT` applications are editable by SALES; ADMIN bypasses.

**PATCH /applications/{id}/submit** — no body. Moves `DRAFT` to `SUBMITTED`, sets `submitted_at`. Errors 400 if not a draft.

### Reviews

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/applications/{id}/reviews` | Bearer | Decision history, newest first |
| POST | `/applications/{id}/reviews` | REVIEWER, ADMIN | Record a decision |

**POST /applications/{id}/reviews**

```json
{
  "action": "APPROVE",
  "decision": "LOW",
  "comment": "Clean history, approved with monitoring."
}
```

Errors:

- 400 — application is not in `SUBMITTED` or `UNDER_REVIEW` status
- 403 — caller is not REVIEWER or ADMIN
- 404 — application not found

### Pagination envelope

Every list endpoint returns:

```json
{
  "data": [ /* items */ ],
  "meta": {
    "total": 120,
    "page": 1,
    "limit": 10,
    "total_pages": 12,
    "has_next": true,
    "has_prev": false
  }
}
```

---

## 10. Error Responses

FastAPI returns two error shapes:

**Simple errors** (raised explicitly by handlers):

```json
{ "detail": "Invalid credentials" }
```

**Validation errors** (from Pydantic, HTTP 422):

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "contact_email"],
      "msg": "value is not a valid email address",
      "input": "user@host"
    }
  ]
}
```

The frontend parses both shapes — see the UI `info.md` for the parser.

---

## 11. Configuration

Environment variables (read by `config.py` via `pydantic-settings`):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://merchant_user:merchant_pass@postgres:5432/merchant_portal` | SQLAlchemy connection string |
| `JWT_ACCESS_SECRET` | `dev-access-secret-change-in-production` | Access token signing key |
| `JWT_REFRESH_SECRET` | `dev-refresh-secret-change-in-production` | Refresh token signing key |
| `JWT_ACCESS_EXPIRES_MINUTES` | `15` | Access token lifetime |
| `JWT_REFRESH_EXPIRES_DAYS` | `7` | Refresh token lifetime |
| `CORS_ORIGINS` | `http://localhost:4200` | Comma-separated allowed origins |

`docker-compose.yml` overrides these for the container. `.env` is used for local runs outside Docker.

---

## 12. Database Lifecycle

Tables are created at app startup via `Base.metadata.create_all(bind=engine)` in the `lifespan` handler.

**This is a development convenience, not a migration strategy.** `create_all` creates missing tables but never alters existing ones. Any change to `models.py` requires a full reset:

```bash
docker compose down -v
docker compose up -d --build
docker compose exec api python -m app.seed
docker compose exec api python -m app.seed_demo
```

For a production deployment, replace `create_all` with Alembic migrations. The models are already structured to support it — `Base.metadata` is the single source of truth.

---

## 13. Seeding

### Default users — `python -m app.seed`

Idempotent. Creates three users if they don't already exist:

| Email | Role | Password |
|---|---|---|
| sales@example.com | SALES | password123 |
| reviewer@example.com | REVIEWER | password123 |
| admin@example.com | ADMIN | password123 |

Safe to re-run. Skips users that exist.

### Demo data — `python -m app.seed_demo`

Generates 120 applications (60 per sales rep) with matching review history. Truncates `applications` and `reviews` first, so re-running resets to a clean demo state. Users and refresh tokens are preserved.

Requires `python -m app.seed` to have run first (creates `sales2@example.com`, which the demo script uses).

Expected output:

```
Demo seed complete.
  Users:        4
  Applications: 120
  Reviews:      90

  Status breakdown:
    APPROVED       42
    DRAFT          18
    REJECTED       12
    SUBMITTED      30
    UNDER_REVIEW   18
```

---

## 14. Running Locally

### Docker (recommended)

```bash
docker compose up -d --build
docker compose exec api python -m app.seed
docker compose exec api python -m app.seed_demo
```

API at `http://localhost:3000/api`. Docs at `http://localhost:3000/docs`.

### Common commands

| Task | Command |
|---|---|
| Start everything | `docker compose up -d` |
| Stop everything | `docker compose down` |
| Stop and wipe DB | `docker compose down -v` |
| Rebuild API | `docker compose up -d --build api` |
| Live API logs | `docker compose logs -f api` |
| Seed default users | `docker compose exec api python -m app.seed` |
| Seed demo data | `docker compose exec api python -m app.seed_demo` |
| Postgres shell | `docker compose exec postgres psql -U merchant_user -d merchant_portal` |
| List tables | `docker compose exec postgres psql -U merchant_user -d merchant_portal -c "\dt"` |

---

## 15. Security Posture

### Implemented

- bcrypt password hashing (72-byte truncation per bcrypt spec)
- JWT access + refresh token model with rotation
- Refresh tokens persisted server-side so they can be invalidated
- Role-based access control enforced on every protected route
- Row-level checks so SALES cannot access other reps' applications
- CORS restricted to configured origins
- Pydantic validation on every request body
- SQL injection prevented by SQLAlchemy parameterized queries

### Not implemented (demo limitations — see section 2)

- Rate limiting on auth endpoints
- Token family revocation on logout / password change
- Email verification
- Audit logging
- HTTPS termination
- Admin-gated signup

---

## 16. Roadmap

Ordered by impact for a production release.

1. **Alembic migrations** — replace `create_all` with versioned migrations. The models are already structured for it.
2. **Rate limiting** — `slowapi` or gateway-level limits on `/auth/*`.
3. **Token family revocation** — track issued refresh tokens in a family; revoke the family on logout or password change.
4. **Audit log table** — record every state change with actor, timestamp, and diff.
5. **Admin-gated signup** — signup creates a SALES account; role changes require an admin action.
6. **Email verification** — confirmation link before the account can log in.
7. **Soft deletes** — replace `ON DELETE CASCADE` with a `deleted_at` timestamp on applications.
8. **Observability** — structured logs (JSON), request IDs, metrics endpoint.
9. **Integration tests** — pytest + httpx against an ephemeral Postgres.
10. **OpenAPI client generation** — codegen the TypeScript client from `/openapi.json` so the frontend models stay in sync.