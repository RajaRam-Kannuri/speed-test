"""Application settings, loaded from environment variables (prefix LLX_)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLX_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://lorvenlax:lorvenlax@localhost:5432/lorvenlax"
    redis_url: str = "redis://localhost:6379/0"

    # Fernet key (urlsafe base64, 32 bytes) used to encrypt secrets at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    secret_key: str = "dev-only-insecure-key-change-me"
    encryption_key: str = ""

    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:3000"

    # Execution engine
    engine_dir: Path = REPO_ROOT / "engine"
    runs_dir: Path = REPO_ROOT / "engine" / ".runs"
    node_binary: str = "node"
    max_run_seconds: int = 900
    default_test_timeout_ms: int = 30_000
    max_parallel_workers: int = 4

    # Network policy. Comma-separated hostnames that may be reached even if they
    # resolve to private addresses (e.g. a sample app inside docker compose).
    allowed_private_hosts: str = ""

    # Artifact storage: "local" or "s3"
    storage_backend: str = "local"
    storage_local_root: Path = REPO_ROOT / "backend" / ".artifacts"
    s3_endpoint_url: str = ""
    s3_bucket: str = "lorvenlax-artifacts"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    # AI provider: "anthropic" or "none" (deterministic agents only)
    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"

    # Celery: run tasks inline (tests only)
    celery_eager: bool = False

    # Quotas and rate limits
    default_monthly_test_runs: int = 5000
    rate_limit_auth_per_minute: int = 20
    rate_limit_jobs_per_minute: int = 30

    @property
    def allowed_private_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_private_hosts.split(",") if h.strip()}

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider == "anthropic" and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
