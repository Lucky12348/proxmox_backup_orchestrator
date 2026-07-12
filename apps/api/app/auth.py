"""Single-user JWT authentication for local PBO deployments."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.hash import bcrypt
from pydantic import BaseModel


AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "true").strip().lower() not in {
    "false",
    "0",
    "no",
}
AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD_HASH: str = os.getenv("AUTH_PASSWORD_HASH", "")
_INSECURE_DEFAULT_SECRET_KEY = "change-me-in-production-use-a-long-random-string"
AUTH_SECRET_KEY: str = os.getenv("AUTH_SECRET_KEY", _INSECURE_DEFAULT_SECRET_KEY)
AUTH_ALGORITHM: str = "HS256"
MAX_AUTH_TOKEN_EXPIRE_MINUTES: int = 180
AUTH_TOKEN_EXPIRE_MINUTES: int = min(
    int(os.getenv("AUTH_TOKEN_EXPIRE_MINUTES", str(MAX_AUTH_TOKEN_EXPIRE_MINUTES))),
    MAX_AUTH_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    auto_error=False,
)

# Lightweight in-process login lockout. Single-user deployments run one uvicorn
# worker (see infra/docker/api.Dockerfile), so a module-level dict is sufficient
# to slow down brute-force attempts against the single admin account.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300
_login_attempts_lock = Lock()
_login_attempts: dict[str, list[float]] = defaultdict(list)


def _login_client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _prune_attempts(key: str, now: float) -> list[float]:
    attempts = [attempt for attempt in _login_attempts[key] if now - attempt < LOGIN_WINDOW_SECONDS]
    _login_attempts[key] = attempts
    return attempts


def _assert_login_not_locked_out(key: str) -> None:
    now = time.monotonic()
    with _login_attempts_lock:
        if len(_prune_attempts(key, now)) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again later.",
            )


def _register_failed_login(key: str) -> None:
    now = time.monotonic()
    with _login_attempts_lock:
        _prune_attempts(key, now).append(now)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


def validate_auth_settings() -> None:
    """Fail startup early when authentication is enabled but incomplete."""
    if not AUTH_ENABLED:
        return

    password_hash = AUTH_PASSWORD_HASH.strip()
    if not password_hash:
        raise RuntimeError(
            "AUTH_ENABLED=true but AUTH_PASSWORD_HASH is empty. "
            "Generate one with: py scripts/generate_password_hash.py"
        )

    if len(password_hash) < 50 or not password_hash.startswith("$2"):
        raise RuntimeError(
            "AUTH_PASSWORD_HASH does not look like a complete bcrypt hash. "
            "It must start with '$2' and be at least 50 characters long. "
            "If this value is in a docker-compose .env file, escape every '$' as '$$'."
        )

    if AUTH_SECRET_KEY == _INSECURE_DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "AUTH_ENABLED=true but AUTH_SECRET_KEY was left at its insecure default. "
            "Anyone who reads the source code can forge a valid admin JWT with it. "
            "Generate one with: openssl rand -hex 32"
        )

    if len(AUTH_SECRET_KEY) < 32:
        raise RuntimeError(
            "AUTH_SECRET_KEY is too short (must be at least 32 characters). "
            "Generate one with: openssl rand -hex 32"
        )


def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    if not hashed:
        return False
    try:
        return bcrypt.verify(plain, hashed)
    except Exception:
        return False


def _create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, AUTH_SECRET_KEY, algorithm=AUTH_ALGORITHM)


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)]) -> str:
    """Validate the Bearer JWT and return the username."""
    if not AUTH_ENABLED:
        return AUTH_USERNAME

    if token is None:
        raise credentials_exception

    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


CurrentUser = Annotated[str, Depends(get_current_user)]


@router.post("/token", response_model=Token)
async def login(request: Request, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    """Exchange username and password for a JWT Bearer token."""
    invalid_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not AUTH_ENABLED:
        token = _create_access_token(
            {"sub": form_data.username},
            timedelta(minutes=AUTH_TOKEN_EXPIRE_MINUTES),
        )
        return Token(access_token=token, token_type="bearer")

    client_key = _login_client_key(request)
    _assert_login_not_locked_out(client_key)

    if form_data.username != AUTH_USERNAME or not _verify_password(form_data.password, AUTH_PASSWORD_HASH):
        _register_failed_login(client_key)
        raise invalid_exc

    token = _create_access_token(
        {"sub": form_data.username},
        timedelta(minutes=AUTH_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=token, token_type="bearer")
