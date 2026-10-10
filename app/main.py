from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import applications, auth, reviews, users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create tables on startup (fine for dev / take-home; use Alembic in prod)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Merchant Portal API",
    version="1.0.0",
    description=(
        "Backend for the Merchant Portal senior-frontend take-home assignment. "
        "Roles: SALES, REVIEWER, ADMIN. "
        "Auth: JWT access + refresh tokens."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")


@app.get("/api/health", tags=["Health"])
def health():
    return {"status": "ok"}