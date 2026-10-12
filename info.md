# Merchant Portal API — Technical Overview

This document is the single source of truth for the backend codebase. Any AI or human reading it should be able to understand the architecture, conventions, and business rules without opening a single source file.

---

## 1. Purpose

A REST API for a merchant payments portal. Manages users, merchant applications, reviewer assignments, and risk review decisions across three user roles (SALES, REVIEWER, ADMIN). Built with FastAPI + SQLAlchemy 2.0 + PostgreSQL.

---

## 2. Demo notice

This is a **demonstration build**, not a hardened production deployment. Mechanisms a production release would require are deliberately simplified:

- **Signup is open** — anyone can create an account with any role, including ADMIN. Production signup would be invite-only, admin-gated, or restricted to a low-privilege default role.
- **JWT secrets committed as defaults** in `docker-compose.yml`. Production deployments must inject strong, per-environment secrets.
- **No rate limiting** on `/auth/login`, `/auth/signup`, or `/auth/refresh`.
- **No token family revocation.** Logout deletes the refresh token row, but tokens issued before deletion remain valid until expiry.
- **No audit log** beyond the `reviews` table.
- **No email verification** on signup.
- **HTTP in dev** — production must terminate TLS at a reverse proxy.

Everything else — authentication, RBAC, workflow rules, pagination, validation — is production-grade.

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
  seed_demo.py      Demo data seeder (120 applications + reviews + assignments)
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
- **`models.py`** — ORM tables and enums. No business logic.
- **`schemas.py`** — Pydantic models for request validation and response serialization.
- **`security.py`** — Password hashing (`bcrypt`) and JWT signing/verification.
- **`deps.py`** — `get_current_user` and `require_roles(...)`.
- **`routers/*`** — HTTP layer, one router per resource.
- **`main.py`** — App factory, CORS, exception handling, route registration.

### Conventions

- **Routers are thin.** Business logic lives in the router function or small pure helpers within the same file. No separate service layer.
- **Dependencies for auth.** Every protected route uses `Depends(get_current_user)` or `Depends(require_roles(...))`.
- **Row-level checks in the router.** SALES/REVIEWER visibility is enforced by query filters or explicit `if` checks.
- **Enums everywhere.** Status, roles, actions, and decisions are Python `enum.Enum` classes backed by Postgres enums.
- **Schemas, not dicts.** Every request body and response is a Pydantic model.
- **Transactions via `db.commit()`** at the end of each write handler.

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
id                    string (uuid)   PK
merchant_name         string
business_type         string
annual_revenue        float
contact_email         string
contact_phone         string
status                enum            DRAFT | SUBMITTED | UNDER_REVIEW | APPROVED | REJECTED
risk_score            float  NULL
risk_decision         enum   NULL     LOW | MEDIUM | HIGH | REJECTED
submitted_at          timestamptz NULL
sales_rep_id          string          FK -> users.id, indexed
assigned_reviewer_id  string  NULL    FK -> users.id, indexed
assigned_at           timestamptz NULL
created_at            timestamptz
updated_at            timestamptz
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

---

## 6. Authentication

### Token model

- **Access token:** JWT, 15-minute expiry, signed with `JWT_ACCESS_SECRET`. Contains `{ sub, email, role, type: "access", iat, exp }`.
- **Refresh token:** JWT, 7-day expiry, signed with `JWT_REFRESH_SECRET`. Contains `{ sub, email, role, type: "refresh", iat, exp }`.
- **Storage:** Refresh tokens are stored in the `refresh_tokens` table. Each row is single-use.
- **Rotation:** Every `/auth/refresh` call deletes the old refresh token row and issues a new pair.

### Flow

```
1. Client POSTs /auth/login
2. Server verifies bcrypt hash
3. Server signs access + refresh tokens
4. Server persists the refresh token
5. Client stores both tokens
6. Client sends Authorization: Bearer <access>
7. On 401, client POSTs /auth/refresh
8. Server validates the refresh token is in the DB and not expired
9. Server deletes the old row and issues a new pair
10. Client retries the original request
```

### Dependencies

- `get_current_user` — decodes the bearer token, validates `type == "access"`, loads the user from the DB.
- `require_roles(*roles)` — factory returning a dependency that checks `user.role` is in the allowed set.

---

## 7. Roles & Permissions

### SALES

- Create merchant applications (status starts at `DRAFT`)
- Edit their own `DRAFT` applications via PATCH
- Submit their own `DRAFT` applications
- List and view their own applications only
- View review history for their own applications
- Cannot record reviewer decisions
- Cannot assign reviewers
- Cannot delete applications

### REVIEWER

- List and view **only applications assigned to them**
- Record review actions on their assigned applications when the status is `SUBMITTED` or `UNDER_REVIEW`
- Cannot create, edit, submit, or delete applications
- Cannot list users

### ADMIN

- List and view **all applications**
- Assign applications to reviewers (autocomplete over REVIEWER users)
- Unassign reviewers
- Record decisions on any `SUBMITTED` or `UNDER_REVIEW` application
- Delete applications (cascades to reviews)
- List users, change a user's role, delete users (with guards — see §12)
- Create and edit applications

### Enforcement

Two layers, always:

1. **Route dependency** — `require_roles(...)` on the endpoint.
2. **Row-level check** — SALES limited to own rows, REVIEWER limited to assigned rows. Enforced in the query filter for list endpoints and via `_ensure_can_view` for detail access.

---

## 8. Workflow — Application Lifecycle

### Status transitions

| From | Trigger | To |
|---|---|---|
| — | SALES/ADMIN creates | DRAFT |
| DRAFT | SALES/ADMIN submits | SUBMITTED |
| SUBMITTED | Reviewer action `APPROVE` | APPROVED |
| SUBMITTED | Reviewer action `REJECT` | REJECTED |
| SUBMITTED | Reviewer action `UNDER_REVIEW` | UNDER_REVIEW |
| UNDER_REVIEW | Reviewer action `APPROVE` | APPROVED |
| UNDER_REVIEW | Reviewer action `REJECT` | REJECTED |
| UNDER_REVIEW | Reviewer action `UNDER_REVIEW` | UNDER_REVIEW |

Terminal states reject further actions with 400.

### Assignment rules

- DRAFT applications cannot be assigned.
- Only users with the `REVIEWER` role can be assigned.
- Assignment sets `assigned_at`; unassignment clears both.
- Assigning is idempotent — reassigning to a different reviewer overwrites.

### Action vs decision

A review record carries two independent fields:

- **`action`** — `APPROVE`, `REJECT`, or `UNDER_REVIEW`. Drives the resulting status.
- **`decision`** — `LOW`, `MEDIUM`, `HIGH`, or `REJECTED`. The reviewer's risk assessment.

This separation lets a HIGH-risk merchant be approved with a comment, or a LOW-risk merchant be rejected for a business reason.

### Side effects of `POST /applications/:id/reviews`

1. Insert a row in `reviews`.
2. Update `status` to the mapped status.
3. Update `risk_decision` to the new decision.
4. Bump `updated_at`.

All four happen in one transaction.

---

## 9. API Reference

Base URL: `http://localhost:3000/api`
Interactive docs: `/docs`, `/redoc`, `/openapi.json`

### Health

| Method | Path | Auth |
|---|---|---|
| GET | `/health` | Public |

### Auth

| Method | Path | Auth |
|---|---|---|
| POST | `/auth/signup` | Public |
| POST | `/auth/login` | Public |
| POST | `/auth/refresh` | Public |
| GET | `/auth/me` | Bearer |

### Users (ADMIN only)

| Method | Path | Description |
|---|---|---|
| GET | `/users` | Paginated list, filter by `role` |
| PATCH | `/users/{id}/role` | Change another user's role |
| DELETE | `/users/{id}` | Delete another user |

**Safety guards on user endpoints:**

- Cannot act on your own account (self-lockout prevention).
- Cannot demote or delete the last remaining ADMIN.
- Cannot delete a user who owns applications or has recorded reviews.

### Applications

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/applications` | Bearer | Paginated list, role-scoped |
| GET | `/applications/{id}` | Bearer | Single application |
| POST | `/applications` | SALES, ADMIN | Create DRAFT |
| PATCH | `/applications/{id}` | SALES, ADMIN | Update DRAFT |
| PATCH | `/applications/{id}/submit` | SALES, ADMIN | DRAFT → SUBMITTED |
| PATCH | `/applications/{id}/assign` | ADMIN | Assign/unassign reviewer |
| DELETE | `/applications/{id}` | ADMIN | Delete application |

**GET /applications query parameters:**

- `page` — integer ≥ 1, default 1
- `limit` — 1–100, default 10
- `status` — one of `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`
- `search` — case-insensitive substring match on `merchant_name` or `contact_email`

**ApplicationOut** embeds `sales_rep` and `assigned_reviewer` as `UserSummary` objects so clients don't need extra requests to render creator/assignee names.

**PATCH /applications/{id}/assign**

```json
// Assign
{ "reviewer_id": "rev-uuid" }

// Unassign
{ "reviewer_id": null }
```

### Reviews

| Method | Path | Auth |
|---|---|---|
| GET | `/applications/{id}/reviews` | Bearer |
| POST | `/applications/{id}/reviews` | REVIEWER, ADMIN |

**POST body:**

```json
{
  "action": "APPROVE",
  "decision": "LOW",
  "comment": "Clean history."
}
```

REVIEWER can only act on their assigned applications. ADMIN can act on any actionable application.

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

Two shapes:

**Simple errors:**

```json
{ "detail": "Invalid credentials" }
```

**Validation errors (422):**

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

The frontend parses both shapes — see the UI `info.md`.

---

## 11. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | postgres connection string | SQLAlchemy |
| `JWT_ACCESS_SECRET` | dev secret | Sign access tokens |
| `JWT_REFRESH_SECRET` | dev secret | Sign refresh tokens |
| `JWT_ACCESS_EXPIRES_MINUTES` | 15 | Access token lifetime |
| `JWT_REFRESH_EXPIRES_DAYS` | 7 | Refresh token lifetime |
| `CORS_ORIGINS` | `http://localhost:4200` | Comma-separated origins |

`docker-compose.yml` overrides these for the container.

---

## 12. Database Lifecycle

Tables are created at startup via `Base.metadata.create_all(bind=engine)` in the `lifespan` handler.

**This is a development convenience, not a migration strategy.** `create_all` creates missing tables but never alters existing ones. Any change to `models.py` requires a full reset:

```bash
docker compose down -v
docker compose up -d --build
docker compose exec api python -m app.seed
docker compose exec api python -m app.seed_demo
```

For production, replace with Alembic migrations.

---

## 13. Seeding

### Default users — `python -m app.seed`

Idempotent. Creates:

| Email | Role | Password |
|---|---|---|
| sales@example.com | SALES | password123 |
| reviewer@example.com | REVIEWER | password123 |
| admin@example.com | ADMIN | password123 |

### Demo data — `python -m app.seed_demo`

Generates 120 applications (60 per sales rep), assigns non-draft applications to the seed reviewer, and creates matching review history. Truncates applications and reviews first; users and refresh tokens are preserved.

Requires `python -m app.seed` to have run first (creates `sales2@example.com`).

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

```bash
docker compose up -d --build
docker compose exec api python -m app.seed
docker compose exec api python -m app.seed_demo
```

API at `http://localhost:3000/api`. Docs at `http://localhost:3000/docs`.

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose down` |
| Full reset | `docker compose down -v && docker compose up -d --build` |
| Rebuild API | `docker compose up -d --build api` |
| Logs | `docker compose logs -f api` |
| Seed default | `docker compose exec api python -m app.seed` |
| Seed demo | `docker compose exec api python -m app.seed_demo` |
| Postgres shell | `docker compose exec postgres psql -U merchant_user -d merchant_portal` |

---

## 15. Security Posture

### Implemented

- bcrypt password hashing (72-byte truncation)
- JWT access + refresh with rotation and DB-backed invalidation
- Role-based access control on every protected route
- Row-level checks for SALES and REVIEWER visibility
- Assignment-gated reviewer actions
- Admin self-lockout and last-admin guards
- Application deletion cascades cleanly to reviews
- CORS restricted to configured origins
- Pydantic validation on every request body
- SQL injection prevented by SQLAlchemy parameterized queries

### Not implemented (see §2)

- Rate limiting on auth endpoints
- Token family revocation
- Email verification
- Audit logging
- HTTPS termination
- Admin-gated signup

---

## 16. Roadmap

1. **Alembic migrations** — replace `create_all`.
2. **Rate limiting** — `slowapi` or gateway-level on `/auth/*`.
3. **Token family revocation** — track issued refresh tokens by family.
4. **Audit log table** — actor, timestamp, diff for every state change.
5. **Admin-gated signup** — signup creates a SALES account; role changes require an admin.
6. **Email verification.**
7. **Soft deletes** — `deleted_at` on applications.
8. **Observability** — structured logs, request IDs, metrics.
9. **Integration tests** — pytest + httpx against an ephemeral Postgres.
10. **OpenAPI client codegen** — generate the TS client so frontend models stay in sync.