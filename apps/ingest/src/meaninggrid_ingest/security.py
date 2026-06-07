"""Password hashing (bcrypt) + session tokens (JWT HS256)."""

from __future__ import annotations

import time

import bcrypt
import jwt

_ALGO = "HS256"


def hash_password(password: str) -> str:
    # bcrypt has a 72-byte input limit
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user_id: str, secret: str, expiry_hours: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + expiry_hours * 3600}, secret, algorithm=_ALGO
    )


def decode_token(token: str, secret: str) -> str | None:
    try:
        return jwt.decode(token, secret, algorithms=[_ALGO]).get("sub")
    except jwt.PyJWTError:
        return None
