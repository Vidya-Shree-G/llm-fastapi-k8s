from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.security import check_rate_limit, get_current_principal, require_scopes

REQUEST_COUNT = Counter(
    "fastapi_http_requests_total",
    "Total number of HTTP requests processed by the FastAPI app",
    labelnames=("method", "path", "status"),
)
REQUEST_LATENCY = Histogram(
    "fastapi_http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=("method", "path"),
)
REQUEST_ERRORS = Counter(
    "fastapi_http_errors_total",
    "Total number of HTTP errors returned by the FastAPI app",
    labelnames=("method", "path", "status"),
)
APP_HEALTH = Gauge("fastapi_app_health", "Application health status. 1 means healthy.")
APP_READY = Gauge("fastapi_app_ready", "Application readiness status. 1 means ready.")

security_scheme = HTTPBearer(
    auto_error=False,
    description="JWT access token issued by the trusted OIDC provider (issuer and audience must match the configured values).",
)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={"persistAuthorization": True},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
async def startup_event() -> None:
    APP_HEALTH.set(1)
    APP_READY.set(1)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration = time.perf_counter() - start_time
        REQUEST_COUNT.labels(method=request.method, path=request.url.path, status="500").inc()
        REQUEST_LATENCY.labels(method=request.method, path=request.url.path).observe(duration)
        REQUEST_ERRORS.labels(method=request.method, path=request.url.path, status="500").inc()
        raise

    duration = time.perf_counter() - start_time
    status_code = str(response.status_code)
    REQUEST_COUNT.labels(method=request.method, path=request.url.path, status=status_code).inc()
    REQUEST_LATENCY.labels(method=request.method, path=request.url.path).observe(duration)
    if response.status_code >= 400:
        REQUEST_ERRORS.labels(method=request.method, path=request.url.path, status=status_code).inc()
    return response


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > settings.max_body_bytes:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": "Request body exceeds the allowed size."},
                    )
            except ValueError:
                pass
    return await call_next(request)


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10_000)
    max_tokens: int = Field(default=100, ge=1, le=512)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("prompt must not be blank")
        return value


@app.get("/health")
async def health() -> dict[str, str]:
    APP_HEALTH.set(1)
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    APP_READY.set(1)
    return {"status": "ready"}


@app.post("/generate")
async def generate(
    request: GenerateRequest,
    _: None = Depends(check_rate_limit),
    claims: dict[str, Any] = Depends(require_scopes("llm:generate")),
):
    del claims

    payload = {
        "model": "Qwen/Qwen2.5-0.5B-Instruct",
        "messages": [{"role": "user", "content": request.prompt}],
        "max_tokens": request.max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.vllm_url}/v1/chat/completions",
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The upstream LLM service is unavailable.",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The upstream LLM service returned an error.",
        )

    data = response.json()
    return {"response": data["choices"][0]["message"]["content"]}


@app.get("/whoami")
async def whoami(claims: dict[str, Any] = Depends(get_current_principal)) -> dict[str, Any]:
    scope_values = set()
    raw_scope = claims.get("scope")
    if isinstance(raw_scope, str):
        scope_values.update(part for part in raw_scope.split() if part)

    raw_scp = claims.get("scp")
    if isinstance(raw_scp, str):
        scope_values.update(part for part in raw_scp.split() if part)
    elif isinstance(raw_scp, list):
        scope_values.update(str(part) for part in raw_scp if part)

    raw_roles = claims.get("roles")
    if isinstance(raw_roles, list):
        scope_values.update(str(part) for part in raw_roles if part)

    return {
        "subject": claims.get("sub"),
        "issuer": claims.get("iss"),
        "audience": claims.get("aud"),
        "scopes": sorted(scope_values),
    }


app.openapi_schema = None


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = app.openapi()
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT access token from the configured OIDC provider.",
        }
    }
    for path in schema.get("paths", {}).values():
        for method in path.values():
            if isinstance(method, dict):
                method.setdefault("security", [{"BearerAuth": []}])
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
