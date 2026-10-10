from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"
_BCRYPT_MAX_BYTES = 72


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _encode(payload: dict, secret: str) -> str:
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def create_access_token(user_id: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.jwt_access_expires_minutes)).timestamp()
        ),
    }
    return _encode(payload, settings.jwt_access_secret)


def create_refresh_token(user_id: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(days=settings.jwt_refresh_expires_days)).timestamp()
        ),
    }
    return _encode(payload, settings.jwt_refresh_secret)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_access_secret, algorithms=[ALGORITHM])


def decode_refresh_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_refresh_secret, algorithms=[ALGORITHM])