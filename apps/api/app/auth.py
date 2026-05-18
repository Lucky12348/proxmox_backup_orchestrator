"""Single-user JWT authentication for local PBO deployments."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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
AUTH_SECRET_KEY: str = os.getenv(
    "AUTH_SECRET_KEY",
    "change-me-in-production-use-a-long-random-string",
)
AUTH_ALGORITHM: str = "HS256"
AUTH_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("AUTH_TOKEN_EXPIRE_MINUTES", "480"))

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    auto_error=False,
)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


def validate_auth_settings() -> None:
    """Fail startup early when authentication is enabled but incomplete."""
    if AUTH_ENABLED and not AUTH_PASSWORD_HASH.strip():
        raise RuntimeError(
            "AUTH_ENABLED=true but AUTH_PASSWORD_HASH is empty. "
            "Generate one with: py scripts/generate_password_hash.py"
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
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
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

    if form_data.username != AUTH_USERNAME:
        raise invalid_exc

    if not _verify_password(form_data.password, AUTH_PASSWORD_HASH):
        raise invalid_exc

    token = _create_access_token(
        {"sub": form_data.username},
        timedelta(minutes=AUTH_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=token, token_type="bearer")
