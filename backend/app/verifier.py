from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from app.alerts import send_alert_webhook
from app.config import Settings
from app.db import Database
from app.metrics import MetricsRegistry
from app.prober import ProberManager, calculate_p95
from app.rollback import RollbackContext, RollbackResult, get_rollback_executor

logger = logging.getLogger("rollwatch.verifier")


class DeploymentVerifier:
    """Runs post-deploy SLO verification windows and orchestrates automated & manual rollbacks."""

    def __init__(
        self,
        db: Database,
        prober: ProberManager,
        metrics: MetricsRegistry,
        settings: Settings,
        *,
        probe_fn: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        rollback_factory: Callable[[str, Settings], Any] | None = None,
    ) -> None:
        self.db = db
        self.prober = prober
        self.metrics = metrics
        self.settings = settings
        self._probe_fn = probe_fn
        self._rollback_factory = rollback_factory or get_rollback_executor
        self._active_tasks: dict[str, asyncio.Task[None]] = {}

    async def stop(self) -> None:
        tasks = list(self._active_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_tasks.clear()

    async def start_verification(
        self,
        *,
        target_id: str,
        commit_sha: str,
        image_tag: str,
        previous_image_tag: str | None = None,
    ) -> dict[str, Any]:
        target = await self.db.get_target(target_id)
        if target is None:
            raise KeyError(f"Target {target_id} not found")

        # Cancel any prior in-flight verification for the same target
        existing = self._active_tasks.pop(target_id, None)
        if existing and not existing.done():
            existing.cancel()
            await asyncio.gather(existing, return_exceptions=True)

        await self.db.update_target_expected_sha(target_id, commit_sha)
        await self.db.update_target_status(target_id, "verifying")
        deployment = await self.db.create_deployment(
            target_id=target_id,
            commit_sha=commit_sha,
            image_tag=image_tag,
            previous_image_tag=previous_image_tag,
            state="verifying",
            summary=f"Verifying {image_tag} ({commit_sha[:7]}) for {target['verify_window_sec']}s",
        )

        task = asyncio.create_task(
            self._run_verification_window(target_id=target_id, deployment_id=deployment["id"]),
            name=f"rollwatch-verify-{deployment['id']}",
        )
        self._active_tasks[target_id] = task
        return deployment

    async def wait_for_target(self, target_id: str) -> None:
        """Await completion of an active verification task (useful in tests)."""
        task = self._active_tasks.get(target_id)
        if task is not None:
            await task

    async def _execute_probe(self, target_id: str) -> dict[str, Any]:
        if self._probe_fn is not None:
            return await self._probe_fn(target_id)
        return await self.prober.probe_once(target_id, skip_status_update=True)

    async def _run_verification_window(self, *, target_id: str, deployment_id: str) -> None:
        try:
            target = await self.db.get_target(target_id)
            deployment = await self.db.get_deployment(deployment_id)
            if target is None or deployment is None:
                return

            window_sec = max(1.0, float(target["verify_window_sec"]))
            probe_interval = max(0.05, float(self.settings.verify_probe_interval_sec))
            max_p95_ms = float(target["slo_max_p95_ms"])
            max_error_rate = float(target["slo_max_error_rate"])

            started = time.monotonic()
            deadline = started + window_sec
            window_probes: list[dict[str, Any]] = []

            while True:
                probe = await self._execute_probe(target_id)
                window_probes.append(probe)

                total_count = len(window_probes)
                failed_count = sum(1 for item in window_probes if not item["is_success"])
                error_rate = failed_count / total_count
                latencies = [float(item["total_ms"]) for item in window_probes if item["is_success"] and item.get("total_ms") is not None]
                p95_ms = calculate_p95(latencies)

                slo_breached = False
                trigger_reason: str | None = None
                if error_rate > max_error_rate:
                    slo_breached = True
                    trigger_reason = "slo_error_rate"
                elif p95_ms is not None and p95_ms > max_p95_ms:
                    slo_breached = True
                    trigger_reason = "slo_latency"

                if slo_breached and trigger_reason is not None:
                    await self._handle_verification_failure(
                        target=target,
                        deployment=deployment,
                        trigger_reason=trigger_reason,
                        p95_ms=p95_ms,
                        error_rate=error_rate,
                        total_probes=total_count,
                        failed_probes=failed_count,
                        last_probe=probe,
                    )
                    return

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(probe_interval, remaining))

            # Full window passed green
            total_count = len(window_probes)
            failed_count = sum(1 for item in window_probes if not item["is_success"])
            error_rate = failed_count / total_count if total_count else 0.0
            latencies = [float(item["total_ms"]) for item in window_probes if item["is_success"] and item.get("total_ms") is not None]
            p95_ms = calculate_p95(latencies)

            summary = (
                f"Verified after {total_count} probes: "
                f"p95={p95_ms if p95_ms is not None else 'n/a'}ms (limit {max_p95_ms}ms), "
                f"error_rate={error_rate:.1%} (limit {max_error_rate:.1%})"
            )
            await self.db.update_deployment(deployment_id, state="verified", summary=summary)
            await self.db.update_target_status(target_id, "healthy")
            await self.db.resolve_open_incidents(target_id, ["slo_latency", "slo_error_rate", "target_down"])
            logger.info("Deployment %s for %s verified: %s", deployment_id, target["name"], summary)
        except asyncio.CancelledError:
            logger.info("Verification task cancelled for target %s deployment %s", target_id, deployment_id)
            raise
        except Exception as exc:
            logger.exception("Unexpected error during deployment verification %s: %s", deployment_id, exc)
            await self.db.update_deployment(deployment_id, state="failed", summary=f"Verification error: {exc}")
            await self.db.update_target_status(target_id, "degraded")
        finally:
            current = self._active_tasks.get(target_id)
            if current is asyncio.current_task():
                self._active_tasks.pop(target_id, None)

    async def _handle_verification_failure(
        self,
        *,
        target: dict[str, Any],
        deployment: dict[str, Any],
        trigger_reason: str,
        p95_ms: float | None,
        error_rate: float,
        total_probes: int,
        failed_probes: int,
        last_probe: dict[str, Any],
    ) -> None:
        target_id = target["id"]
        rollback_tag = deployment.get("previous_image_tag") or deployment["image_tag"]
        executor = self._rollback_factory(target["rollback_type"], self.settings)
        rollback_result: RollbackResult = await executor.execute(
            RollbackContext(
                target_id=target_id,
                target_name=target["name"],
                failed_sha=deployment["commit_sha"],
                rollback_to_tag=rollback_tag,
                config=target.get("rollback_config") or {},
            )
        )

        if rollback_result.executed:
            self.metrics.record_rollback(
                target_id=target_id,
                target_name=target["name"],
                rollback_type=rollback_result.adapter,
                success=rollback_result.success,
            )

        deployment_state = "rolled_back" if (rollback_result.executed and rollback_result.success) else "failed"
        summary = (
            f"Breached {trigger_reason}: p95={p95_ms}ms (max {target['slo_max_p95_ms']}ms), "
            f"error_rate={error_rate:.1%} (max {target['slo_max_error_rate']:.1%}). "
            f"Rollback ({rollback_result.adapter}): {'executed' if rollback_result.executed else 'not configured'}."
        )
        await self.db.update_deployment(deployment["id"], state=deployment_state, summary=summary)
        await self.db.update_target_status(target_id, "down" if not last_probe["is_success"] else "degraded")

        metrics_snapshot = {
            "p95_ms": p95_ms,
            "error_rate": round(error_rate, 4),
            "total_probes": total_probes,
            "failed_probes": failed_probes,
            "slo_max_p95_ms": target["slo_max_p95_ms"],
            "slo_max_error_rate": target["slo_max_error_rate"],
            "image_tag": deployment["image_tag"],
            "previous_image_tag": deployment.get("previous_image_tag"),
            "last_status_code": last_probe.get("status_code"),
            "last_error": last_probe.get("error_msg"),
            "rollback_adapter": rollback_result.adapter,
            "rollback_dry_run": rollback_result.dry_run,
            "rollback_command_id": rollback_result.command_id,
        }

        await self.db.create_incident(
            target_id=target_id,
            deployment_id=deployment["id"],
            trigger_reason=trigger_reason,
            offending_sha=deployment["commit_sha"],
            metrics_snapshot=metrics_snapshot,
            rollback_executed=rollback_result.executed,
            rollback_output=rollback_result.output,
        )

        await send_alert_webhook(
            target.get("alert_webhook_url"),
            title=f"Deployment Rollback ({deployment_state})",
            target_name=target["name"],
            trigger_reason=trigger_reason,
            details={
                "offending_sha": deployment["commit_sha"][:7],
                "p95_ms": p95_ms,
                "error_rate": f"{error_rate:.1%}",
                "rollback_to": rollback_tag,
                "adapter": rollback_result.adapter,
                "dry_run": rollback_result.dry_run,
            },
            severity="critical",
        )

    async def trigger_manual_rollback(
        self,
        target_id: str,
        *,
        rollback_to_tag: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        target = await self.db.get_target(target_id)
        if target is None:
            raise KeyError(f"Target {target_id} not found")

        deployments = await self.db.list_deployments(target_id, limit=5)
        latest_deployment = deployments[0] if deployments else None

        chosen_tag = rollback_to_tag
        if not chosen_tag and latest_deployment:
            chosen_tag = latest_deployment.get("previous_image_tag") or latest_deployment.get("image_tag")
        chosen_tag = chosen_tag or "previous-stable"

        failed_sha = latest_deployment["commit_sha"] if latest_deployment else target.get("expected_git_sha")

        # Cancel active verification if running
        existing = self._active_tasks.pop(target_id, None)
        if existing and not existing.done():
            existing.cancel()
            await asyncio.gather(existing, return_exceptions=True)

        executor = self._rollback_factory(target["rollback_type"], self.settings)
        result: RollbackResult = await executor.execute(
            RollbackContext(
                target_id=target_id,
                target_name=target["name"],
                failed_sha=failed_sha,
                rollback_to_tag=chosen_tag,
                config=target.get("rollback_config") or {},
            )
        )

        if result.executed:
            self.metrics.record_rollback(
                target_id=target_id,
                target_name=target["name"],
                rollback_type=result.adapter,
                success=result.success,
            )

        if latest_deployment and latest_deployment["state"] == "verifying":
            await self.db.update_deployment(
                latest_deployment["id"],
                state="rolled_back" if result.success else "failed",
                summary=f"Manual rollback triggered to {chosen_tag}: {reason or 'operator action'}",
            )

        recent = await self.db.get_recent_probes(target_id, limit=20)
        latencies = [float(p["total_ms"]) for p in recent if p["is_success"] and p.get("total_ms") is not None]
        p95_ms = calculate_p95(latencies)
        error_rate = sum(1 for p in recent if not p["is_success"]) / len(recent) if recent else 0.0

        incident = await self.db.create_incident(
            target_id=target_id,
            deployment_id=latest_deployment["id"] if latest_deployment else None,
            trigger_reason="version_drift" if target["status"] == "drifted" else "slo_error_rate",
            offending_sha=failed_sha,
            metrics_snapshot={
                "manual_rollback": True,
                "reason": reason or "Manual operator rollback from dashboard",
                "rollback_to_tag": chosen_tag,
                "p95_ms": p95_ms,
                "error_rate": round(error_rate, 4),
                "rollback_adapter": result.adapter,
                "rollback_dry_run": result.dry_run,
                "rollback_command_id": result.command_id,
            },
            rollback_executed=result.executed,
            rollback_output=result.output,
        )

        if target["status"] == "verifying":
            await self.db.update_target_status(target_id, "degraded")

        await send_alert_webhook(
            target.get("alert_webhook_url"),
            title="Manual Rollback Triggered",
            target_name=target["name"],
            trigger_reason=reason or "manual_rollback",
            details={
                "rollback_to": chosen_tag,
                "adapter": result.adapter,
                "dry_run": result.dry_run,
                "success": result.success,
            },
            severity="warning",
        )

        return {
            "target_id": target_id,
            "adapter": result.adapter,
            "rollback_to_tag": chosen_tag,
            "executed": result.executed,
            "dry_run": result.dry_run,
            "success": result.success,
            "command_id": result.command_id,
            "output": result.output,
            "incident_id": incident["id"],
        }
