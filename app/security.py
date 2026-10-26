from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends.cryptography_backend import CryptographyBackend

from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


class RateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str) -> bool:
        now = time.monotonic()
        window_start = now - 60

        async with self._lock:
            bucket = self._buckets[client_id]
            while bucket and bucket[0] < window_start:
                bucket.popleft()

            if len(bucket) >= self.limit_per_minute:
                return False

            bucket.append(now)
            return True


rate_limiter = RateLimiter(settings.max_requests_per_minute)


def _coerce_scopes(claims: dict[str, Any]) -> set[str]:
    scopes: set[str] = set()

    scope_value = claims.get("scope")
    if isinstance(scope_value, str):
        scopes.update(part for part in scope_value.split() if part)

    scp_value = claims.get("scp")
    if isinstance(scp_value, str):
        scopes.update(part for part in scp_value.split() if part)
    elif isinstance(scp_value, list):
        scopes.update(str(part) for part in scp_value if part)

    roles = claims.get("roles", [])
    if isinstance(roles, list):
        scopes.update(str(role) for role in roles if role)

    return scopes


class OIDCValidator:
    def __init__(self) -> None:
        self._jwks_cache: dict[str, Any] | None = None
        self._expires_at = 0.0

    async def _load_jwks(self) -> dict[str, Any]:
        if settings.oidc_jwks_url is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC JWKS configuration is missing.",
            )

        now = time.monotonic()
        if self._jwks_cache is not None and now < self._expires_at:
            return self._jwks_cache

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.oidc_jwks_url)
            response.raise_for_status()
            data = response.json()

        self._jwks_cache = data
        self._expires_at = now + settings.token_cache_seconds
        return data

    async def validate_token(self, token: str) -> dict[str, Any]:
        if not settings.auth_enabled:
            return {"sub": "local-dev", "scope": " ".join(settings.required_scopes)}

        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token header.") from exc

        alg = header.get("alg")
        if alg not in settings.allowed_algorithms:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token algorithm: {alg}",
            )

        key_id = header.get("kid")
        if not key_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing key id.")

        try:
            jwks = await self._load_jwks()
            matching_key = next(
                (key for key in jwks.get("keys", []) if key.get("kid") == key_id),
                None,
            )
            if matching_key is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No matching JWK found.")

            public_key = CryptographyBackend().rsa_key_from_jwk(json.dumps(matching_key))
            claims = jwt.decode(
                token,
                public_key,
                algorithms=settings.allowed_algorithms,
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (JWTError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from exc

        if not claims.get("sub"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is missing a subject.")

        return claims


validator = OIDCValidator()


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if not settings.auth_enabled:
        return {"sub": "local-dev", "scope": " ".join(settings.required_scopes)}

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = await validator.validate_token(credentials.credentials)
    return claims


def require_scopes(*required: str):
    required_scopes = tuple(required) or tuple(settings.required_scopes)

    async def dependency(claims: dict[str, Any] = Depends(get_current_principal)) -> dict[str, Any]:
        scopes = _coerce_scopes(claims)
        missing = [scope for scope in required_scopes if scope not in scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope(s): {', '.join(missing)}",
            )
        return claims

    return dependency


async def check_rate_limit(request: Request) -> None:
    client_id = request.client.host if request.client else "unknown"
    if not await rate_limiter.is_allowed(client_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please retry later.",
        )
