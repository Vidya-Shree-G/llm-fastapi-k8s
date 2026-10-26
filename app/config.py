from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LLM API"
    environment: str = "production"
    auth_mode: Literal["oidc", "disabled"] = "disabled"
    vllm_url: str = "http://vllm:8000"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    required_scopes: list[str] = Field(default_factory=lambda: ["llm:generate"])
    allowed_algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])
    max_body_bytes: int = 128_000
    max_requests_per_minute: int = 30
    token_cache_seconds: int = 300

    @property
    def auth_enabled(self) -> bool:
        if self.auth_mode == "disabled":
            return False
        return bool(self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url)

    @model_validator(mode="after")
    def validate_auth_config(self):
        if self.auth_mode == "oidc" and not self.auth_enabled:
            raise ValueError(
                "AUTH_MODE=oidc requires OIDC_ISSUER, OIDC_AUDIENCE, and OIDC_JWKS_URL to be set. "
                "Never run the API in production without a trusted external identity provider."
            )
        return self


settings = Settings()
