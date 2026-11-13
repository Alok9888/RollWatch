from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


TargetMode = Literal["external", "managed"]
RollbackType = Literal["none", "aws_ssm", "github_dispatch", "webhook"]
TargetStatus = Literal["healthy", "degraded", "down", "verifying", "drifted"]
DeploymentState = Literal["verifying", "verified", "failed", "rolled_back"]
IncidentTrigger = Literal["slo_latency", "slo_error_rate", "version_drift", "tls_expiry", "target_down"]


class TargetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=4, max_length=2048)
    health_path: str = Field(default="/", max_length=255)
    mode: TargetMode = "external"
    interval_sec: int = Field(default=15, ge=5, le=3600)
    expected_git_sha: str | None = Field(default=None, max_length=64)
    slo_max_p95_ms: float = Field(default=1000.0, gt=0, le=60000)
    slo_max_error_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    verify_window_sec: int = Field(default=60, ge=5, le=1800)
    rollback_type: RollbackType = "none"
    rollback_config: dict[str, Any] = Field(default_factory=dict)
    alert_webhook_url: str | None = Field(default=None, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return cleaned.rstrip("/")

    @field_validator("health_path")
    @classmethod
    def validate_health_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            return "/"
        if not cleaned.startswith("/"):
            return f"/{cleaned}"
        return cleaned

    @field_validator("expected_git_sha", "alert_webhook_url")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DeploymentOut(BaseModel):
    id: str
    target_id: str
    commit_sha: str
    image_tag: str
    previous_image_tag: str | None = None
    state: DeploymentState
    started_at: str
    completed_at: str | None = None
    summary: str | None = None


class TargetOut(BaseModel):
    id: str
    name: str
    url: str
    health_path: str
    mode: TargetMode
    interval_sec: int
    expected_git_sha: str | None = None
    slo_max_p95_ms: float
    slo_max_error_rate: float
    verify_window_sec: int
    rollback_type: RollbackType
    rollback_config: dict[str, Any] = Field(default_factory=dict)
    alert_webhook_url: str | None = None
    status: TargetStatus
    created_at: str
    # Live enriched telemetry from recent probes & deployments
    current_p95_ms: float | None = None
    current_error_rate: float | None = None
    latest_total_ms: float | None = None
    latest_ttfb_ms: float | None = None
    latest_status_code: int | None = None
    tls_expiry_days: int | None = None
    live_git_sha: str | None = None
    version_drift: bool = False
    header_drift: bool = False
    baseline_headers_hash: str | None = None
    latest_headers_hash: str | None = None
    last_checked_at: str | None = None
    active_deployment: DeploymentOut | None = None


class ProbeResultOut(BaseModel):
    id: int
    target_id: str
    status_code: int | None = None
    dns_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    total_ms: float | None = None
    tls_expiry_days: int | None = None
    live_git_sha: str | None = None
    headers_hash: str | None = None
    error_msg: str | None = None
    is_success: bool
    checked_at: str


class IncidentOut(BaseModel):
    id: str
    target_id: str
    target_name: str | None = None
    deployment_id: str | None = None
    trigger_reason: IncidentTrigger
    offending_sha: str | None = None
    metrics_snapshot: dict[str, Any] = Field(default_factory=dict)
    rollback_executed: bool
    rollback_output: str | None = None
    created_at: str
    resolved_at: str | None = None


class DeployWebhookPayload(BaseModel):
    target_id: str = Field(..., min_length=1)
    commit_sha: str = Field(..., min_length=1, max_length=64)
    image_tag: str = Field(..., min_length=1, max_length=255)
    previous_image_tag: str | None = Field(default=None, max_length=255)


class ManualRollbackRequest(BaseModel):
    rollback_to_tag: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=255)


class RollbackExecutionOut(BaseModel):
    target_id: str
    adapter: str
    rollback_to_tag: str
    executed: bool
    dry_run: bool
    success: bool
    command_id: str | None = None
    output: str
    incident_id: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    git_sha: str
    db: Literal["ok", "error"]
