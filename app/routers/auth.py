from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import RefreshToken, User
from app.schemas import (
    RefreshTokenRequest,
    TokenResponse,
    UserLogin,
    UserOut,
    UserSignup,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserSignup, db: Session = Depends(get_db)):
    """Register a new user with a given role. Returns access + refresh tokens."""
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        name=payload.name,
        role=payload.role,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _issue_tokens(user, db)


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Authenticate with email and password."""
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return _issue_tokens(user, db)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new token pair. Rotates the refresh token."""
    try:
        claims = decode_refresh_token(payload.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    stored = (
        db.query(RefreshToken).filter(RefreshToken.token == payload.refresh_token).first()
    )
    if not stored:
        raise HTTPException(status_code=401, detail="Refresh token not recognized")

    now = datetime.now(timezone.utc)
    expires = stored.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        db.delete(stored)
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.get(User, claims["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    db.delete(stored)
    db.commit()
    return _issue_tokens(user, db)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return current_user


def _issue_tokens(user: User, db: Session) -> TokenResponse:
    access = create_access_token(user.id, user.email, user.role.value)
    refresh = create_refresh_token(user.id, user.email, user.role.value)

    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_expires_days
    )
    db.add(RefreshToken(token=refresh, user_id=user.id, expires_at=expires_at))
    db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserOut.model_validate(user),
    )