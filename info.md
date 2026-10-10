# Merchant Portal Frontend — Technical Overview

This document is the single source of truth for the codebase. Any AI or human
reading it should be able to understand the architecture, conventions, and
backend contract without opening a single source file.

---

## 1. Purpose

A merchant payments portal frontend built with Angular 20. Supports three user
roles (SALES, REVIEWER, ADMIN) across a multi-step merchant application wizard,
a review workflow, and a paginated dashboard.

This is a take-home assignment. Maximum effort: 6–8 hours. The rubric weights
RxJS/interceptors/autosave (20%), architecture (15%), forms (15%), security
(15%), testing (15%), UX (10%), API integration (5%), code quality (5%).

---

## 2. Tech Stack

- Angular 20, standalone components, zoneless change detection
- Signals + computed + effect for state; RxJS for streams
- Reactive Forms (typed, with custom validators)
- Tailwind CSS v4 (config via @theme in styles.scss; no tailwind.config.js)
- SCSS only for global theme tokens and rare cases Tailwind cannot express
- Vitest + Angular TestBed for unit tests
- TypeScript strict mode

---

## 3. Backend Contract

The frontend talks to a FastAPI backend. Reference file: `API_REFERENCE.md` in
the backend repo. Summary below.

**Base URL:** http://localhost:3000/api

### Auth

- POST /auth/signup      → { access_token, refresh_token, user }
- POST /auth/login       → { access_token, refresh_token, user }
- POST /auth/refresh     → { access_token, refresh_token, user }
- GET  /auth/me          → User                (Bearer required)

Access tokens expire in 15 minutes. Refresh tokens expire in 7 days and are
rotated on every use (single-use). Concurrent 401s must trigger exactly one
refresh call; queued requests retry with the new token.

### Roles

- SALES:    creates/edits own applications; sees only their own
- REVIEWER: views all applications; records risk decisions
- ADMIN:    full access

### Applications

- GET    /applications                (paginated, filter by status + search)
- GET    /applications/:id
- POST   /applications                (SALES/ADMIN)
- PATCH  /applications/:id            (SALES/ADMIN, DRAFT only)
- PATCH  /applications/:id/submit     (SALES/ADMIN, DRAFT → SUBMITTED)

### Reviews

- GET  /applications/:id/reviews
- POST /applications/:id/reviews      (REVIEWER/ADMIN)

### Pagination envelope

All list endpoints return:

    {
      "data": [ ...items ],
      "meta": { "total", "page", "limit", "total_pages", "has_next", "has_prev" }
    }

Query params: page (>=1, default 1), limit (1–100, default 10).

### Enums

ApplicationStatus: DRAFT | SUBMITTED | UNDER_REVIEW | APPROVED | REJECTED
RiskDecision:      LOW | MEDIUM | HIGH | REJECTED
UserRole:          SALES | REVIEWER | ADMIN

---

## 4. Architecture

### Folder layout

    src/
      environments/            API base URL config
      app/
        app.ts                 root component (router-outlet only)
        app.config.ts          providers: router, http, interceptors
        app.routes.ts          top-level routes (lazy-loaded features)
        core/                  singletons: auth, http, api clients, models
        shared/                reusable UI: components, directives, pipes
        layout/                app shell: header, nav
        features/              lazy-loaded feature areas

### Layer responsibilities

- core/     No UI. Services, guards, interceptors, API clients, models.
- shared/   No business logic. Reusable, presentational, standalone.
- layout/   The persistent shell around routed views.
- features/ One folder per user-facing area. Each has its own routes file.

### Data flow (read)

    HTTP response (RxJS stream)
      -> toSignal() or resource()
      -> signal consumed by template
      -> template renders via @if / @for

### Data flow (write)

    Form value
      -> debounced stream (autosave) or explicit submit
      -> API client
      -> HttpClient
      -> interceptor adds Bearer token
      -> response updates a signal / store

### Declarative conventions

- Signals for state: signal(), computed(), effect(), linkedSignal()
- RxJS only where streams earn their place: HTTP, debounce, pagination
- No subscriptions in components; use toSignal() or the async pipe
- Functional guards (CanActivateFn), functional resolvers, functional interceptors
- input(), output(), model() for component I/O — no @Input/@Output decorators
- inject() in field initializers — no constructor injection
- @if / @for / @switch in templates — no *ngIf/*ngFor

---

## 5. Security

### Token storage

Tokens are stored in localStorage under a single key ("mp.session"). This is
the pragmatic choice for a take-home. In a production app we would move the
refresh token to an HttpOnly cookie set by the backend, keeping only the access
token in memory. Tradeoff documented here so reviewers can see we know the
difference.

### Role gating

Two layers:

1. UI gating: the `*appHasRole` structural directive hides elements.
2. Route gating: functional `roleGuard(['REVIEWER','ADMIN'])` on routes.

Both are UX only. The backend enforces authorization on every request. A user
who tampers with localStorage sees the wrong UI but cannot perform any action
the backend rejects.

### Sensitive field masking

The `MaskedFieldComponent` masks values by default. Reveal requires clicking a
button; the reveal is not persisted. Roles with permission see masked values
and can reveal individually.

### Content Security Policy

The production build should ship with a CSP header. This app is compatible
with:

    default-src 'self';
    script-src 'self';
    style-src 'self' 'unsafe-inline';
    img-src 'self' data:;
    connect-src 'self' http://localhost:3000;
    frame-ancestors 'none';
    base-uri 'self';
    form-action 'self';

`style-src 'unsafe-inline'` is required because Tailwind injects style tags in
dev. In production with a compiled stylesheet this can be tightened to
`style-src 'self'`.

---

## 6. Running the app

    npm install
    npm start        # dev server on http://localhost:4200

Backend must be running at http://localhost:3000/api.

Test accounts (from backend seed):

    sales@example.com     / password123
    reviewer@example.com  / password123
    admin@example.com     / password123

---

## 7. Testing

Vitest + Angular TestBed. Test files sit beside the code they test.

- *.spec.ts for unit tests

Focus areas by value:

1. authInterceptor: concurrent 401 → one refresh call, all retried
2. Autosave: debounce, retry-on-error, no state loss
3. roleGuard: blocks wrong roles, allows correct ones
4. Wizard: step validation prevents advancing with invalid data
5. MaskedField: hidden by default, reveals on click

---

## 8. AI disclosure

AI coding assistance was used during development. All code has been reviewed,
understood, and can be explained line-by-line. Verification was performed by
running the app against the live backend and by unit tests.