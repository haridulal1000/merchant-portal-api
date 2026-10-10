# Merchant Portal API — Reference

**Base URL (local):** http://localhost:3000/api
**Swagger UI:** http://localhost:3000/docs
**ReDoc:** http://localhost:3000/redoc
**OpenAPI JSON:** http://localhost:3000/openapi.json

## Roles

- **SALES** — creates/edits own merchant applications; views only their own
- **REVIEWER** — views all applications; records risk decisions
- **ADMIN** — full access; can list users, view/edit all applications

## Auth

JWT access token (15 min) + refresh token (7 days, rotated on use).
Header: `Authorization: Bearer <access_token>`

## Pagination

All list endpoints accept `page` (default 1) and `limit` (default 10, max 100).
Response envelope:

```json
{
  "data": [ ...items ],
  "meta": {
    "total": 42,
    "page": 1,
    "limit": 10,
    "total_pages": 5,
    "has_next": true,
    "has_prev": false
  }
}