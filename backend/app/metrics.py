from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest


class MetricsRegistry:
    """Dedicated Prometheus metrics registry for RollWatch."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.target_up = Gauge(
            "rollwatch_target_up",
            "Whether the monitored target's latest probe succeeded (1=up, 0=down).",
            ["target_id", "target_name", "mode"],
            registry=self.registry,
        )
        self.probe_duration_ms = Gauge(
            "rollwatch_probe_duration_ms",
            "Latest total HTTP probe duration in milliseconds.",
            ["target_id", "target_name", "mode"],
            registry=self.registry,
        )
        self.tls_expiry_days = Gauge(
            "rollwatch_tls_expiry_days",
            "Days remaining until the target TLS certificate expires.",
            ["target_id", "target_name"],
            registry=self.registry,
        )
        self.version_drift = Gauge(
            "rollwatch_version_drift",
            "Whether live git_sha diverges from expected_git_sha (1=drifted, 0=aligned).",
            ["target_id", "target_name"],
            registry=self.registry,
        )
        self.rollbacks_total = Counter(
            "rollwatch_rollbacks_total",
            "Total rollbacks triggered by RollWatch.",
            ["target_id", "target_name", "rollback_type", "status"],
            registry=self.registry,
        )

    def record_probe(
        self,
        *,
        target_id: str,
        target_name: str,
        mode: str,
        is_success: bool,
        total_ms: float | None,
        tls_expiry_days: int | None,
        is_drifted: bool,
    ) -> None:
        self.target_up.labels(target_id=target_id, target_name=target_name, mode=mode).set(1.0 if is_success else 0.0)
        if total_ms is not None:
            self.probe_duration_ms.labels(target_id=target_id, target_name=target_name, mode=mode).set(total_ms)
        if tls_expiry_days is not None:
            self.tls_expiry_days.labels(target_id=target_id, target_name=target_name).set(float(tls_expiry_days))
        self.version_drift.labels(target_id=target_id, target_name=target_name).set(1.0 if is_drifted else 0.0)

    def record_rollback(
        self,
        *,
        target_id: str,
        target_name: str,
        rollback_type: str,
        success: bool,
    ) -> None:
        self.rollbacks_total.labels(
            target_id=target_id,
            target_name=target_name,
            rollback_type=rollback_type,
            status="success" if success else "failed",
        ).inc()

    def clear_target(self, target_id: str) -> None:
        for metric in (self.target_up, self.probe_duration_ms, self.tls_expiry_days, self.version_drift):
            for label_values in list(metric._metrics.keys()):  # noqa: SLF001
                if label_values and label_values[0] == target_id:
                    metric.remove(*label_values)

    def render(self) -> bytes:
        return generate_latest(self.registry)
