# Merchant Portal API

FastAPI + PostgreSQL backend for the Merchant Portal take-home assignment.

## Prerequisites

- Docker Desktop (that's it — no Python, no Postgres needed on your machine)

Verify:

    docker --version
    docker compose version

## First-time setup

Run these once, from the project folder:

    docker compose build
    docker compose up -d postgres

Wait 10 seconds, then:

    docker compose ps

Make sure postgres shows (healthy). Then:

    docker compose up -d api
    docker compose exec api python -m app.seed

## URLs

- Swagger UI:    http://localhost:3000/docs
- ReDoc:         http://localhost:3000/redoc
- OpenAPI JSON:  http://localhost:3000/openapi.json
- Health check:  http://localhost:3000/api/health

## Default users

Password for all: password123

    Email                  Role
    ---------------------  --------
    sales@example.com      SALES
    reviewer@example.com   REVIEWER
    admin@example.com      ADMIN

## Daily commands

Start everything:

    docker compose up -d

Stop everything (keeps data):

    docker compose down

Stop and wipe everything (fresh start):

    docker compose down -v

Restart just the API:

    docker compose restart api

Rebuild API after code change:

    docker compose up -d --build api

View API logs:

    docker compose logs -f api

Check container status:

    docker compose ps

Open a shell inside the API container:

    docker compose exec api bash

## Database commands

Open Postgres prompt (type \q to exit):

    docker compose exec postgres psql -U merchant_user -d merchant_portal

List all tables:

    docker compose exec postgres psql -U merchant_user -d merchant_portal -c "\dt"

List users:

    docker compose exec postgres psql -U merchant_user -d merchant_portal -c "SELECT email, name, role FROM users;"

List applications:

    docker compose exec postgres psql -U merchant_user -d merchant_portal -c "SELECT id, merchant_name, status FROM merchant_applications;"

List reviews:

    docker compose exec postgres psql -U merchant_user -d merchant_portal -c "SELECT id, application_id, decision FROM reviews;"

Clear applications, reviews, and refresh tokens (keeps users):

    docker compose exec postgres psql -U merchant_user -d merchant_portal -c "TRUNCATE reviews, merchant_applications, refresh_tokens RESTART IDENTITY CASCADE;"

Clear everything including users:

    docker compose exec postgres psql -U merchant_user -d merchant_portal -c "TRUNCATE refresh_tokens, reviews, merchant_applications, users RESTART IDENTITY CASCADE;"

## Seeding

Seed the three default users:

    docker compose exec api python -m app.seed

Safe to run multiple times — it will skip users that already exist.

To add a user with a specific role, use the signup endpoint:

    $body = @{ email = "newuser@example.com"; password = "password123"; name = "New User"; role = "REVIEWER" } | ConvertTo-Json
    Invoke-RestMethod -Uri "http://localhost:3000/api/auth/signup" -Method Post -Body $body -ContentType "application/json"

Roles: SALES, REVIEWER, ADMIN.

## Full reset

Wipe the database, rebuild, and reseed in one go:

    docker compose down -v
    docker compose build --no-cache
    docker compose up -d postgres
    Start-Sleep -Seconds 10
    docker compose up -d api
    Start-Sleep -Seconds 5
    docker compose exec api python -m app.seed

Use this whenever models change, since tables are created automatically on startup and existing tables are not altered.

## Quick smoke test

Login:

    $body = @{ email = "sales@example.com"; password = "password123" } | ConvertTo-Json
    $auth = Invoke-RestMethod -Uri "http://localhost:3000/api/auth/login" -Method Post -Body $body -ContentType "application/json"
    $headers = @{ Authorization = "Bearer $($auth.access_token)" }

Create a draft application:

    $app = @{ merchant_name = "Acme Widgets"; business_type = "Retail"; annual_revenue = 250000; contact_email = "hello@acme.test"; contact_phone = "+15551234567" } | ConvertTo-Json
    $created = Invoke-RestMethod -Uri "http://localhost:3000/api/applications" -Method Post -Body $app -ContentType "application/json" -Headers $headers
    $appId = $created.id

List applications with pagination:

    Invoke-RestMethod -Uri "http://localhost:3000/api/applications?page=1&limit=10" -Headers $headers

Submit for review:

    Invoke-RestMethod -Uri "http://localhost:3000/api/applications/$appId/submit" -Method Patch -Headers $headers

Approve as reviewer:

    $rbody = @{ email = "reviewer@example.com"; password = "password123" } | ConvertTo-Json
    $reviewer = Invoke-RestMethod -Uri "http://localhost:3000/api/auth/login" -Method Post -Body $rbody -ContentType "application/json"
    $reviewerHeaders = @{ Authorization = "Bearer $($reviewer.access_token)" }
    $review = @{ decision = "LOW"; comment = "Clean history" } | ConvertTo-Json
    Invoke-RestMethod -Uri "http://localhost:3000/api/applications/$appId/reviews" -Method Post -Body $review -ContentType "application/json" -Headers $reviewerHeaders

## Roles

- SALES:    creates/edits own applications, views only their own
- REVIEWER: views all applications, records risk decisions
- ADMIN:    full access, can list users, edits any application

## Environment variables

Set in docker-compose.yml under the api service.

- DATABASE_URL
- JWT_ACCESS_SECRET
- JWT_REFRESH_SECRET
- JWT_ACCESS_EXPIRES_MINUTES  (default 15)
- JWT_REFRESH_EXPIRES_DAYS    (default 7)
- CORS_ORIGINS                (default http://localhost:4200)

Change the JWT secrets before deploying anywhere real.

## Connecting from Angular

In src/environments/environment.ts:

    export const environment = {
      production: false,
      apiUrl: 'http://localhost:3000/api',
    };

CORS is already configured for http://localhost:4200. If Angular runs on a different port, update CORS_ORIGINS in docker-compose.yml and run:

    docker compose up -d --force-recreate api

## Project layout

    app/
      config.py        settings from env
      database.py      SQLAlchemy engine and session
      models.py        User, MerchantApplication, Review, RefreshToken
      schemas.py       Pydantic request/response models
      security.py      bcrypt hashing, JWT encode/decode
      deps.py          auth dependencies and role guards
      seed.py          default user seeder
      main.py          FastAPI app, CORS, routers
      routers/
        auth.py          /api/auth/*
        users.py         /api/users
        applications.py  /api/applications/*
        reviews.py       /api/applications/{id}/reviews
    Dockerfile
    docker-compose.yml
    requirements.txt
    .env
    .env.example
    API_REFERENCE.md   full endpoint reference
    README.md

## Troubleshooting

docker: command not found
Docker Desktop is not running. Start it and wait for the tray icon to settle.

Port 3000 or 5432 in use
Stop the other process, or change the host ports in docker-compose.yml.

relation "users" does not exist
API hasn't finished starting. Check docker compose logs -f api and wait for "Application startup complete."

Login fails with "Invalid credentials"
Seed the users: docker compose exec api python -m app.seed

Connection refused
Postgres may not be healthy yet. Check docker compose ps and wait for (healthy).

Schema changes not taking effect
Do a full reset (see above). Tables are created on startup and are not altered automatically.

### Demo data (for UI development)

Populate the database with 120 merchant applications (60 per sales rep) and
matching review history so pagination, filters, and search have realistic
data to work against.

    docker compose exec api python -m app.seed_demo

Expected output:

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

The demo seed is idempotent — applications and reviews are wiped before
seeding. Users and their sessions are preserved, so you will not be logged
out.

To restore the minimal 3-user seed with no applications:

    docker compose exec api python -m app.seed