from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

import httpx

from app.alerts import send_alert_webhook
from app.config import Settings
from app.db import Database
from app.metrics import MetricsRegistry

logger = logging.getLogger("rollwatch.prober")

TRACKED_HEADERS = ("server", "content-type", "cache-control")


def calculate_p95(latencies: Sequence[float]) -> float | None:
    """Compute the 95th percentile using linear interpolation."""
    clean = sorted(float(v) for v in latencies if v is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return round(clean[0], 2)
    rank = 0.95 * (len(clean) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return round(clean[lo], 2)
    interpolated = clean[lo] + (clean[hi] - clean[lo]) * (rank - lo)
    return round(interpolated, 2)


def compute_headers_hash(headers: Mapping[str, str]) -> str:
    """Compute a deterministic SHA-256 hash of Server, Content-Type, and Cache-Control."""
    lowered = {k.lower(): v.strip() for k, v in headers.items()}
    canonical = "\n".join(f"{name}:{lowered.get(name, '')}" for name in TRACKED_HEADERS)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def detect_header_drift(baseline_hash: str | None, current_hash: str | None) -> bool:
    """Return True when response header signature differs from the recorded baseline."""
    if not baseline_hash or not current_hash:
        return False
    return baseline_hash != current_hash


def detect_version_drift(
    mode: str,
    expected_git_sha: str | None,
    live_git_sha: str | None,
    *,
    is_verifying: bool = False,
) -> bool:
    """Detect whether a managed target's live git_sha diverges from expected_git_sha."""
    if mode != "managed" or is_verifying:
        return False
    if not expected_git_sha or not live_git_sha:
        return False
    expected = expected_git_sha.strip().lower()
    live = live_git_sha.strip().lower()
    if expected == live:
        return False
    if min(len(expected), len(live)) >= 7 and (live.startswith(expected) or expected.startswith(live)):
        return False
    return True


def build_probe_url(base_url: str, health_path: str) -> str:
    """Build the full URL to probe while preserving explicit paths on external URLs."""
    cleaned_base = base_url.strip().rstrip("/")
    cleaned_path = (health_path or "/").strip()
    if not cleaned_path.startswith("/"):
        cleaned_path = f"/{cleaned_path}"

    parsed = urlparse(cleaned_base)
    if cleaned_path == "/":
        if parsed.path and parsed.path != "/":
            return cleaned_base
        return f"{cleaned_base}/"

    if cleaned_base.endswith(cleaned_path):
        return cleaned_base
    return f"{cleaned_base}{cleaned_path}"


async def measure_dns_ms(host: str, port: int) -> float | None:
    """Measure non-blocking DNS resolution time via asyncio's event loop."""
    loop = asyncio.get_running_loop()
    start = time.perf_counter()
    await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return round((time.perf_counter() - start) * 1000.0, 2)


def _measure_tls_sync(host: str, port: int, timeout_sec: float) -> tuple[float | None, int | None]:
    """Perform a real TLS handshake and parse certificate days remaining."""
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout_sec) as sock:
        sock.settimeout(timeout_sec)
        start = time.perf_counter()
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            tls_ms = round((time.perf_counter() - start) * 1000.0, 2)
            cert = ssock.getpeercert()
            expiry_days: int | None = None
            if cert and "notAfter" in cert:
                expiry_epoch = ssl.cert_time_to_seconds(str(cert["notAfter"]))
                expiry_days = int((expiry_epoch - time.time()) // 86400)
            return tls_ms, expiry_days


@dataclass
class ProbeMeasurement:
    status_code: int | None = None
    dns_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    total_ms: float | None = None
    tls_expiry_days: int | None = None
    live_git_sha: str | None = None
    headers_hash: str | None = None
    error_msg: str | None = None
    is_success: bool = False


async def execute_probe(
    *,
    url: str,
    health_path: str = "/",
    mode: str = "external",
    timeout_sec: float = 10.0,
) -> ProbeMeasurement:
    """Perform a real outbound DNS, TLS (when HTTPS), and HTTP streaming probe."""
    probe_url = build_probe_url(url, health_path)
    parsed = urlparse(probe_url)
    host = parsed.hostname
    scheme = (parsed.scheme or "http").lower()
    port = parsed.port or (443 if scheme == "https" else 80)

    result = ProbeMeasurement()
    if not host:
        result.error_msg = f"Invalid target URL: {probe_url}"
        return result

    # 1. Real DNS lookup
    try:
        result.dns_ms = await asyncio.wait_for(measure_dns_ms(host, port), timeout=min(timeout_sec, 5.0))
    except Exception as exc:
        result.error_msg = f"DNS lookup failed: {exc}"
        return result

    # 2. Real TLS handshake & certificate expiry (HTTPS only)
    if scheme == "https":
        try:
            tls_ms, expiry_days = await asyncio.to_thread(_measure_tls_sync, host, port, min(timeout_sec, 5.0))
            result.tls_ms = tls_ms
            result.tls_expiry_days = expiry_days
        except ssl.SSLCertVerificationError as exc:
            result.error_msg = f"TLS certificate verification failed: {exc}"
            return result
        except Exception as exc:
            result.error_msg = f"TLS handshake failed: {exc}"
            return result

    # 3. Real HTTP streaming request for exact TTFB & total duration
    try:
        timeout = httpx.Timeout(timeout_sec)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            t0 = time.perf_counter()
            async with client.stream("GET", probe_url, headers={"User-Agent": "RollWatch/1.0"}) as response:
                result.ttfb_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                body_bytes = await response.aread()
                result.total_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                result.status_code = response.status_code
                result.headers_hash = compute_headers_hash(response.headers)

                http_ok = 200 <= response.status_code < 400
                service_healthy = True

                if mode == "managed" and body_bytes:
                    try:
                        payload = json.loads(body_bytes.decode("utf-8", errors="ignore"))
                        if isinstance(payload, dict):
                            sha_val = payload.get("git_sha")
                            if isinstance(sha_val, str) and sha_val.strip():
                                result.live_git_sha = sha_val.strip()
                            health_status = payload.get("status")
                            if isinstance(health_status, str) and health_status.lower() not in {
                                "ok",
                                "healthy",
                                "up",
                                "pass",
                            }:
                                service_healthy = False
                                result.error_msg = f"Health endpoint reported status={health_status}"
                    except json.JSONDecodeError:
                        # Ignore non-JSON bodies gracefully
                        pass

                result.is_success = http_ok and service_healthy
                if not http_ok and not result.error_msg:
                    result.error_msg = f"HTTP {response.status_code}"
    except httpx.TimeoutException:
        result.error_msg = f"Request timed out after {timeout_sec:.1f}s"
    except httpx.HTTPError as exc:
        result.error_msg = f"HTTP error: {exc}"
    except Exception as exc:
        result.error_msg = f"Probe error: {exc}"

    return result


class ProberManager:
    """Manages one background asyncio.Task per monitored target plus SQLite retention pruning."""

    def __init__(self, db: Database, metrics: MetricsRegistry, settings: Settings) -> None:
        self.db = db
        self.metrics = metrics
        self.settings = settings
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self._stop_event.clear()
        if self.settings.enable_background_prober:
            targets = await self.db.list_targets()
            for target in targets:
                self.start_target_worker(target["id"])
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="rollwatch-probe-cleanup")
        logger.info("ProberManager started with %d target workers", len(self._tasks))

    async def stop(self) -> None:
        self._stop_event.set()
        tasks: list[asyncio.Task[Any]] = list(self._tasks.values())
        if self._cleanup_task is not None:
            tasks.append(self._cleanup_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._cleanup_task = None
        logger.info("ProberManager stopped cleanly")

    def start_target_worker(self, target_id: str) -> None:
        if not self.settings.enable_background_prober:
            return
        existing = self._tasks.get(target_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._worker_loop(target_id), name=f"rollwatch-probe-{target_id}")
        self._tasks[target_id] = task

    async def stop_target_worker(self, target_id: str) -> None:
        task = self._tasks.pop(target_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.metrics.clear_target(target_id)

    async def _cleanup_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                deleted = await self.db.prune_old_probes(self.settings.retention_hours)
                if deleted:
                    logger.info("Pruned %d probe results older than %dh", deleted, self.settings.retention_hours)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Probe cleanup loop error: %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.cleanup_interval_sec)
            except asyncio.TimeoutError:
                continue

    async def _worker_loop(self, target_id: str) -> None:
        while not self._stop_event.is_set():
            interval_sec = 15
            try:
                target = await self.db.get_target(target_id)
                if target is None:
                    return
                interval_sec = max(5, int(target["interval_sec"]))
                if target["status"] != "verifying":
                    await self.probe_once(target_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Unhandled error in probe worker for %s: %s", target_id, exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_sec)
            except asyncio.TimeoutError:
                continue

    async def probe_once(self, target_id: str, *, skip_status_update: bool = False) -> dict[str, Any]:
        target = await self.db.get_target(target_id)
        if target is None:
            raise KeyError(f"Target {target_id} not found")

        measurement = await execute_probe(
            url=target["url"],
            health_path=target["health_path"],
            mode=target["mode"],
            timeout_sec=self.settings.probe_timeout_sec,
        )

        stored = await self.db.insert_probe_result(
            target_id=target_id,
            status_code=measurement.status_code,
            dns_ms=measurement.dns_ms,
            tls_ms=measurement.tls_ms,
            ttfb_ms=measurement.ttfb_ms,
            total_ms=measurement.total_ms,
            tls_expiry_days=measurement.tls_expiry_days,
            live_git_sha=measurement.live_git_sha,
            headers_hash=measurement.headers_hash,
            error_msg=measurement.error_msg,
            is_success=measurement.is_success,
        )

        is_verifying = target["status"] == "verifying"
        is_drifted = detect_version_drift(
            target["mode"],
            target.get("expected_git_sha"),
            measurement.live_git_sha,
            is_verifying=is_verifying,
        )

        self.metrics.record_probe(
            target_id=target_id,
            target_name=target["name"],
            mode=target["mode"],
            is_success=measurement.is_success,
            total_ms=measurement.total_ms,
            tls_expiry_days=measurement.tls_expiry_days,
            is_drifted=is_drifted,
        )

        if not skip_status_update and not is_verifying:
            await self._evaluate_target_health(target, stored, is_drifted)

        return stored

    async def _evaluate_target_health(
        self,
        target: dict[str, Any],
        latest_probe: dict[str, Any],
        is_drifted: bool,
    ) -> None:
        target_id = target["id"]
        recent = await self.db.get_recent_probes(target_id, limit=20)
        latencies = [p["total_ms"] for p in recent if p["is_success"] and p["total_ms"] is not None]
        p95_ms = calculate_p95(latencies)
        error_rate = sum(1 for p in recent if not p["is_success"]) / len(recent) if recent else 0.0
        tls_days = latest_probe.get("tls_expiry_days")
        tls_expiring = tls_days is not None and tls_days <= self.settings.tls_expiry_warning_days

        if not latest_probe["is_success"]:
            new_status = "down"
            if await self.db.get_open_incident(target_id, "target_down") is None:
                snapshot = {
                    "status_code": latest_probe.get("status_code"),
                    "error_msg": latest_probe.get("error_msg"),
                    "p95_ms": p95_ms,
                    "error_rate": round(error_rate, 4),
                }
                await self.db.create_incident(
                    target_id=target_id,
                    trigger_reason="target_down",
                    offending_sha=latest_probe.get("live_git_sha") or target.get("expected_git_sha"),
                    metrics_snapshot=snapshot,
                )
                await send_alert_webhook(
                    target.get("alert_webhook_url"),
                    title="Target Down",
                    target_name=target["name"],
                    trigger_reason="target_down",
                    details=snapshot,
                    severity="critical",
                )
        elif is_drifted:
            new_status = "drifted"
            await self.db.resolve_open_incidents(target_id, ["target_down"])
            if await self.db.get_open_incident(target_id, "version_drift") is None:
                snapshot = {
                    "expected_git_sha": target.get("expected_git_sha"),
                    "live_git_sha": latest_probe.get("live_git_sha"),
                    "p95_ms": p95_ms,
                }
                await self.db.create_incident(
                    target_id=target_id,
                    trigger_reason="version_drift",
                    offending_sha=latest_probe.get("live_git_sha"),
                    metrics_snapshot=snapshot,
                )
                await send_alert_webhook(
                    target.get("alert_webhook_url"),
                    title="Version Drift Detected",
                    target_name=target["name"],
                    trigger_reason="version_drift",
                    details=snapshot,
                    severity="warning",
                )
        elif (
            tls_expiring
            or (p95_ms is not None and p95_ms > float(target["slo_max_p95_ms"]))
            or error_rate > float(target["slo_max_error_rate"])
        ):
            new_status = "degraded"
            await self.db.resolve_open_incidents(target_id, ["target_down", "version_drift"])
            if tls_expiring and await self.db.get_open_incident(target_id, "tls_expiry") is None:
                snapshot = {
                    "tls_expiry_days": tls_days,
                    "warning_threshold_days": self.settings.tls_expiry_warning_days,
                }
                await self.db.create_incident(
                    target_id=target_id,
                    trigger_reason="tls_expiry",
                    metrics_snapshot=snapshot,
                )
                await send_alert_webhook(
                    target.get("alert_webhook_url"),
                    title="TLS Certificate Expiring Soon",
                    target_name=target["name"],
                    trigger_reason="tls_expiry",
                    details=snapshot,
                    severity="warning",
                )
        else:
            new_status = "healthy"
            await self.db.resolve_open_incidents(target_id, ["target_down", "version_drift", "tls_expiry"])

        if new_status != target["status"]:
            await self.db.update_target_status(target_id, new_status)
