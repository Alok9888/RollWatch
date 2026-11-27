from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _parse_origins(raw: str) -> list[str]:
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://rollwatch.vercel.app",
    ]


def _default_db_path() -> str:
    explicit = os.getenv("ROLLWATCH_DB_PATH")
    if explicit:
        return explicit
    if os.getenv("VERCEL"):
        return "/tmp/rollwatch.db"
    return "./data/rollwatch.db"


def _default_background_prober() -> bool:
    explicit = os.getenv("ROLLWATCH_ENABLE_BACKGROUND_PROBER")
    if explicit is not None:
        return explicit.lower() in {"1", "true", "yes", "on"}
    # On serverless runtimes (e.g. Vercel Functions), run probes on-demand and during deploy verification
    return not bool(os.getenv("VERCEL"))


def _default_git_sha() -> str:
    return os.getenv("GIT_SHA") or os.getenv("VERCEL_GIT_COMMIT_SHA") or "dev"


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=_default_db_path)
    webhook_secret: str = field(default_factory=lambda: os.getenv("ROLLWATCH_WEBHOOK_SECRET", "dev-webhook-secret"))
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_origins(
            os.getenv(
                "ROLLWATCH_CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000,https://rollwatch.vercel.app",
            )
        )
    )
    git_sha: str = field(default_factory=_default_git_sha)
    github_token: str | None = field(default_factory=lambda: os.getenv("GITHUB_TOKEN") or None)
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "us-east-1"))
    probe_timeout_sec: float = field(default_factory=lambda: float(os.getenv("ROLLWATCH_PROBE_TIMEOUT_SEC", "10.0")))
    tls_expiry_warning_days: int = field(
        default_factory=lambda: int(os.getenv("ROLLWATCH_TLS_EXPIRY_WARNING_DAYS", "14"))
    )
    retention_hours: int = field(default_factory=lambda: int(os.getenv("ROLLWATCH_RETENTION_HOURS", "24")))
    cleanup_interval_sec: int = field(default_factory=lambda: int(os.getenv("ROLLWATCH_CLEANUP_INTERVAL_SEC", "300")))
    verify_probe_interval_sec: float = field(
        default_factory=lambda: float(os.getenv("ROLLWATCH_VERIFY_PROBE_INTERVAL_SEC", "5.0"))
    )
    enable_background_prober: bool = field(default_factory=_default_background_prober)


def get_settings() -> Settings:
    return Settings()
