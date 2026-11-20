from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.config import Settings
from app.db import Database
from app.metrics import MetricsRegistry
from app.prober import ProberManager
from app.rollback import RollbackContext, RollbackExecutor, RollbackResult
from app.verifier import DeploymentVerifier


@dataclass
class RecordingRollbackExecutor(RollbackExecutor):
    adapter_name: str = "aws_ssm"
    should_succeed: bool = True
    calls: list[RollbackContext] | None = None

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    async def execute(self, context: RollbackContext) -> RollbackResult:
        assert self.calls is not None
        self.calls.append(context)
        return RollbackResult(
            adapter=self.adapter_name,
            executed=True,
            dry_run=False,
            success=self.should_succeed,
            command_id="cmd-test-12345",
            output=f"Executed rollback to {context.rollback_to_tag}",
        )


@pytest.mark.asyncio
async def test_verification_succeeds_when_slos_stay_green() -> None:
    settings = Settings(
        db_path=":memory:",
        verify_probe_interval_sec=0.05,
        enable_background_prober=False,
    )
    db = Database(":memory:")
    await db.connect()
    metrics = MetricsRegistry()
    prober = ProberManager(db=db, metrics=metrics, settings=settings)

    async def healthy_probe(target_id: str) -> dict[str, Any]:
        return await db.insert_probe_result(
            target_id=target_id,
            status_code=200,
            dns_ms=4.0,
            tls_ms=12.0,
            ttfb_ms=25.0,
            total_ms=40.0,
            tls_expiry_days=80,
            live_git_sha="1111aaa",
            headers_hash="hash-v1",
            error_msg=None,
            is_success=True,
        )

    recorder = RecordingRollbackExecutor()
    verifier = DeploymentVerifier(
        db=db,
        prober=prober,
        metrics=metrics,
        settings=settings,
        probe_fn=healthy_probe,
        rollback_factory=lambda _rtype, _cfg: recorder,
    )

    try:
        target = await db.create_target(
            name="trace-api",
            url="https://trace.internal",
            health_path="/health",
            mode="managed",
            slo_max_p95_ms=500.0,
            slo_max_error_rate=0.1,
            verify_window_sec=1,
            rollback_type="aws_ssm",
            rollback_config={"instance_id": "i-12345"},
        )

        dep = await verifier.start_verification(
            target_id=target["id"],
            commit_sha="1111aaa",
            image_tag="trace:v2",
            previous_image_tag="trace:v1",
        )
        assert dep["state"] == "verifying"

        await verifier.wait_for_target(target["id"])

        updated_dep = await db.get_deployment(dep["id"])
        updated_target = await db.get_target(target["id"])
        incidents = await db.list_incidents(target_id=target["id"])

        assert updated_dep is not None
        assert updated_dep["state"] == "verified"
        assert updated_dep["completed_at"] is not None
        assert updated_target is not None
        assert updated_target["status"] == "healthy"
        assert updated_target["expected_git_sha"] == "1111aaa"
        assert incidents == []
        assert recorder.calls == []
    finally:
        await verifier.stop()
        await db.close()


@pytest.mark.asyncio
async def test_verification_rolls_back_immediately_on_latency_slo_breach() -> None:
    settings = Settings(
        db_path=":memory:",
        verify_probe_interval_sec=0.05,
        enable_background_prober=False,
    )
    db = Database(":memory:")
    await db.connect()
    metrics = MetricsRegistry()
    prober = ProberManager(db=db, metrics=metrics, settings=settings)

    async def slow_probe(target_id: str) -> dict[str, Any]:
        return await db.insert_probe_result(
            target_id=target_id,
            status_code=200,
            dns_ms=5.0,
            tls_ms=15.0,
            ttfb_ms=650.0,
            total_ms=1450.0,
            tls_expiry_days=80,
            live_git_sha="bad9999",
            headers_hash="hash-v2",
            error_msg=None,
            is_success=True,
        )

    recorder = RecordingRollbackExecutor(adapter_name="aws_ssm")
    verifier = DeploymentVerifier(
        db=db,
        prober=prober,
        metrics=metrics,
        settings=settings,
        probe_fn=slow_probe,
        rollback_factory=lambda _rtype, _cfg: recorder,
    )

    try:
        target = await db.create_target(
            name="trace-api",
            url="https://trace.internal",
            health_path="/health",
            mode="managed",
            slo_max_p95_ms=500.0,
            slo_max_error_rate=0.1,
            verify_window_sec=10,
            rollback_type="aws_ssm",
            rollback_config={"instance_id": "i-99999"},
        )

        dep = await verifier.start_verification(
            target_id=target["id"],
            commit_sha="bad9999",
            image_tag="trace:bad",
            previous_image_tag="trace:good",
        )
        await verifier.wait_for_target(target["id"])

        updated_dep = await db.get_deployment(dep["id"])
        updated_target = await db.get_target(target["id"])
        incidents = await db.list_incidents(target_id=target["id"])

        assert updated_dep is not None
        assert updated_dep["state"] == "rolled_back"
        assert updated_target is not None
        assert updated_target["status"] == "degraded"
        assert len(incidents) == 1
        assert incidents[0]["trigger_reason"] == "slo_latency"
        assert incidents[0]["offending_sha"] == "bad9999"
        assert incidents[0]["rollback_executed"] is True
        assert "trace:good" in (incidents[0]["rollback_output"] or "")
        assert incidents[0]["metrics_snapshot"]["p95_ms"] == 1450.0
        assert recorder.calls is not None and len(recorder.calls) == 1
        assert recorder.calls[0].rollback_to_tag == "trace:good"
        assert b"rollwatch_rollbacks_total" in metrics.render()
    finally:
        await verifier.stop()
        await db.close()


@pytest.mark.asyncio
async def test_verification_rolls_back_immediately_on_error_rate_slo_breach() -> None:
    settings = Settings(
        db_path=":memory:",
        verify_probe_interval_sec=0.05,
        enable_background_prober=False,
    )
    db = Database(":memory:")
    await db.connect()
    metrics = MetricsRegistry()
    prober = ProberManager(db=db, metrics=metrics, settings=settings)

    async def failing_probe(target_id: str) -> dict[str, Any]:
        return await db.insert_probe_result(
            target_id=target_id,
            status_code=503,
            dns_ms=3.0,
            tls_ms=10.0,
            ttfb_ms=20.0,
            total_ms=25.0,
            tls_expiry_days=90,
            live_git_sha=None,
            headers_hash="hash-err",
            error_msg="HTTP 503",
            is_success=False,
        )

    recorder = RecordingRollbackExecutor(adapter_name="github_dispatch")
    verifier = DeploymentVerifier(
        db=db,
        prober=prober,
        metrics=metrics,
        settings=settings,
        probe_fn=failing_probe,
        rollback_factory=lambda _rtype, _cfg: recorder,
    )

    try:
        target = await db.create_target(
            name="checkout-svc",
            url="https://checkout.internal",
            health_path="/health",
            mode="managed",
            slo_max_p95_ms=500.0,
            slo_max_error_rate=0.1,
            verify_window_sec=10,
            rollback_type="github_dispatch",
            rollback_config={"owner": "acme", "repo": "checkout", "workflow": "rollback.yml"},
        )

        dep = await verifier.start_verification(
            target_id=target["id"],
            commit_sha="deadbeef",
            image_tag="checkout:v9",
            previous_image_tag="checkout:v8",
        )
        await verifier.wait_for_target(target["id"])

        updated_dep = await db.get_deployment(dep["id"])
        updated_target = await db.get_target(target["id"])
        incidents = await db.list_incidents(target_id=target["id"])

        assert updated_dep is not None
        assert updated_dep["state"] == "rolled_back"
        assert updated_target is not None
        assert updated_target["status"] == "down"
        assert len(incidents) == 1
        assert incidents[0]["trigger_reason"] == "slo_error_rate"
        assert incidents[0]["metrics_snapshot"]["error_rate"] == 1.0
        assert incidents[0]["rollback_executed"] is True
    finally:
        await verifier.stop()
        await db.close()
