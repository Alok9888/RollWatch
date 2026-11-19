from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST

from app.config import Settings, get_settings
from app.db import Database
from app.metrics import MetricsRegistry
from app.models import (
    DeploymentOut,
    DeployWebhookPayload,
    HealthOut,
    IncidentOut,
    ManualRollbackRequest,
    ProbeResultOut,
    RollbackExecutionOut,
    TargetCreate,
    TargetOut,
)
from app.prober import ProberManager, calculate_p95, detect_header_drift, detect_version_drift
from app.verifier import DeploymentVerifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("rollwatch.api")


async def _enrich_target(db: Database, target: dict[str, Any]) -> TargetOut:
    probes = await db.get_recent_probes(target["id"], limit=30)
    latest = probes[0] if probes else None
    latencies = [float(p["total_ms"]) for p in probes if p["is_success"] and p.get("total_ms") is not None]
    p95_ms = calculate_p95(latencies)
    error_rate = round(sum(1 for p in probes if not p["is_success"]) / len(probes), 4) if probes else None

    baseline_hash = await db.get_baseline_headers_hash(target["id"])
    latest_hash = latest.get("headers_hash") if latest else None
    header_drift = detect_header_drift(baseline_hash, latest_hash)

    live_sha = latest.get("live_git_sha") if latest else None
    if live_sha is None:
        for probe in probes:
            if probe.get("live_git_sha"):
                live_sha = probe["live_git_sha"]
                break

    tls_expiry = latest.get("tls_expiry_days") if latest else None
    if tls_expiry is None:
        for probe in probes:
            if probe.get("tls_expiry_days") is not None:
                tls_expiry = probe["tls_expiry_days"]
                break

    active_dep = await db.get_active_deployment(target["id"])
    version_drift = detect_version_drift(
        target["mode"],
        target.get("expected_git_sha"),
        live_sha,
        is_verifying=(target["status"] == "verifying" or active_dep is not None),
    )

    return TargetOut(
        id=target["id"],
        name=target["name"],
        url=target["url"],
        health_path=target["health_path"],
        mode=target["mode"],
        interval_sec=target["interval_sec"],
        expected_git_sha=target.get("expected_git_sha"),
        slo_max_p95_ms=target["slo_max_p95_ms"],
        slo_max_error_rate=target["slo_max_error_rate"],
        verify_window_sec=target["verify_window_sec"],
        rollback_type=target["rollback_type"],
        rollback_config=target.get("rollback_config") or {},
        alert_webhook_url=target.get("alert_webhook_url"),
        status=target["status"],
        created_at=target["created_at"],
        current_p95_ms=p95_ms,
        current_error_rate=error_rate,
        latest_total_ms=latest.get("total_ms") if latest else None,
        latest_ttfb_ms=latest.get("ttfb_ms") if latest else None,
        latest_status_code=latest.get("status_code") if latest else None,
        tls_expiry_days=tls_expiry,
        live_git_sha=live_sha,
        version_drift=version_drift,
        header_drift=header_drift,
        baseline_headers_hash=baseline_hash,
        latest_headers_hash=latest_hash,
        last_checked_at=latest.get("checked_at") if latest else None,
        active_deployment=DeploymentOut(**active_dep) if active_dep else None,
    )


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    settings = custom_settings or get_settings()
    db = Database(settings.db_path)
    metrics = MetricsRegistry()
    prober = ProberManager(db=db, metrics=metrics, settings=settings)
    verifier = DeploymentVerifier(db=db, prober=prober, metrics=metrics, settings=settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.connect()
        await prober.start()
        app.state.db = db
        app.state.metrics = metrics
        app.state.prober = prober
        app.state.verifier = verifier
        app.state.settings = settings
        try:
            yield
        finally:
            await verifier.stop()
            await prober.stop()
            await db.close()

    app = FastAPI(
        title="RollWatch API",
        description="Deployment-Aware Health, Drift & Auto-Rollback Monitor",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Health & Metrics ---

    @app.get("/health", response_model=HealthOut, tags=["observability"])
    async def health() -> HealthOut:
        db_ok = await db.ping()
        return HealthOut(
            status="ok" if db_ok else "degraded",
            git_sha=settings.git_sha,
            db="ok" if db_ok else "error",
        )

    @app.get("/metrics", tags=["observability"])
    async def prometheus_metrics() -> Response:
        return Response(content=metrics.render(), media_type=CONTENT_TYPE_LATEST)

    # --- Targets CRUD ---

    @app.get("/api/targets", response_model=list[TargetOut], tags=["targets"])
    async def list_targets() -> list[TargetOut]:
        targets = await db.list_targets()
        return [await _enrich_target(db, t) for t in targets]

    @app.post("/api/targets", response_model=TargetOut, status_code=status.HTTP_201_CREATED, tags=["targets"])
    async def create_target(payload: TargetCreate) -> TargetOut:
        created = await db.create_target(
            name=payload.name,
            url=payload.url,
            health_path=payload.health_path,
            mode=payload.mode,
            interval_sec=payload.interval_sec,
            expected_git_sha=payload.expected_git_sha,
            slo_max_p95_ms=payload.slo_max_p95_ms,
            slo_max_error_rate=payload.slo_max_error_rate,
            verify_window_sec=payload.verify_window_sec,
            rollback_type=payload.rollback_type,
            rollback_config=payload.rollback_config,
            alert_webhook_url=payload.alert_webhook_url,
        )
        prober.start_target_worker(created["id"])
        return await _enrich_target(db, created)

    @app.get("/api/targets/{target_id}", response_model=TargetOut, tags=["targets"])
    async def get_target(target_id: str) -> TargetOut:
        target = await db.get_target(target_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
        return await _enrich_target(db, target)

    @app.delete("/api/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["targets"])
    async def delete_target(target_id: str) -> Response:
        await prober.stop_target_worker(target_id)
        deleted = await db.delete_target(target_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/targets/{target_id}/probes", response_model=list[ProbeResultOut], tags=["probes"])
    async def get_target_probes(
        target_id: str,
        limit: int = Query(default=60, ge=1, le=500),
    ) -> list[ProbeResultOut]:
        target = await db.get_target(target_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
        probes = await db.get_recent_probes(target_id, limit=limit)
        return [ProbeResultOut(**p) for p in probes]

    @app.post("/api/targets/{target_id}/check-now", response_model=ProbeResultOut, tags=["probes"])
    async def check_target_now(target_id: str) -> ProbeResultOut:
        target = await db.get_target(target_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
        result = await prober.probe_once(target_id)
        return ProbeResultOut(**result)

    # --- Deployments & Rollbacks ---

    @app.get("/api/targets/{target_id}/deployments", response_model=list[DeploymentOut], tags=["deployments"])
    async def get_target_deployments(target_id: str) -> list[DeploymentOut]:
        target = await db.get_target(target_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
        deployments = await db.list_deployments(target_id)
        return [DeploymentOut(**d) for d in deployments]

    @app.post(
        "/api/webhooks/deploy",
        response_model=DeploymentOut,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["deployments"],
    )
    async def deploy_webhook(
        payload: DeployWebhookPayload,
        x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
    ) -> DeploymentOut:
        if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, settings.webhook_secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

        try:
            deployment = await verifier.start_verification(
                target_id=payload.target_id,
                commit_sha=payload.commit_sha,
                image_tag=payload.image_tag,
                previous_image_tag=payload.previous_image_tag,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        return DeploymentOut(**deployment)

    @app.post("/api/targets/{target_id}/rollback", response_model=RollbackExecutionOut, tags=["deployments"])
    async def manual_rollback(
        target_id: str,
        payload: ManualRollbackRequest | None = None,
    ) -> RollbackExecutionOut:
        req = payload or ManualRollbackRequest()
        try:
            result = await verifier.trigger_manual_rollback(
                target_id,
                rollback_to_tag=req.rollback_to_tag,
                reason=req.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return RollbackExecutionOut(**result)

    # --- Incidents ---

    @app.get("/api/incidents", response_model=list[IncidentOut], tags=["incidents"])
    async def list_incidents(
        target_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[IncidentOut]:
        incidents = await db.list_incidents(target_id=target_id, limit=limit)
        return [IncidentOut(**item) for item in incidents]

    return app


app = create_app()
