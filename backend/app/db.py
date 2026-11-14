from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS targets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    health_path TEXT NOT NULL DEFAULT '/',
    mode TEXT NOT NULL CHECK(mode IN ('external', 'managed')),
    interval_sec INTEGER NOT NULL DEFAULT 15,
    expected_git_sha TEXT,
    slo_max_p95_ms REAL NOT NULL DEFAULT 1000.0,
    slo_max_error_rate REAL NOT NULL DEFAULT 0.1,
    verify_window_sec INTEGER NOT NULL DEFAULT 60,
    rollback_type TEXT NOT NULL DEFAULT 'none' CHECK(rollback_type IN ('none', 'aws_ssm', 'github_dispatch', 'webhook')),
    rollback_config_json TEXT NOT NULL DEFAULT '{}',
    alert_webhook_url TEXT,
    status TEXT NOT NULL DEFAULT 'healthy' CHECK(status IN ('healthy', 'degraded', 'down', 'verifying', 'drifted')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS probe_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    status_code INTEGER,
    dns_ms REAL,
    tls_ms REAL,
    ttfb_ms REAL,
    total_ms REAL,
    tls_expiry_days INTEGER,
    live_git_sha TEXT,
    headers_hash TEXT,
    error_msg TEXT,
    is_success INTEGER NOT NULL,
    checked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_probe_results_target_checked
    ON probe_results(target_id, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_probe_results_checked_at
    ON probe_results(checked_at);

CREATE TABLE IF NOT EXISTS deployments (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    image_tag TEXT NOT NULL,
    previous_image_tag TEXT,
    state TEXT NOT NULL CHECK(state IN ('verifying', 'verified', 'failed', 'rolled_back')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_deployments_target_started
    ON deployments(target_id, started_at DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    deployment_id TEXT REFERENCES deployments(id) ON DELETE SET NULL,
    trigger_reason TEXT NOT NULL CHECK(trigger_reason IN ('slo_latency', 'slo_error_rate', 'version_drift', 'tls_expiry', 'target_down')),
    offending_sha TEXT,
    metrics_snapshot_json TEXT NOT NULL DEFAULT '{}',
    rollback_executed INTEGER NOT NULL DEFAULT 0,
    rollback_output TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_incidents_target_created
    ON incidents(target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_incidents_created
    ON incidents(created_at DESC);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON;")
        await self._conn.execute("PRAGMA journal_mode = WAL;")
        await self._conn.execute("PRAGMA busy_timeout = 5000;")
        await self._migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def _migrate(self) -> None:
        await self.conn.executescript(SCHEMA_SQL)
        async with self.conn.execute("SELECT version FROM schema_migrations WHERE version = 1") as cursor:
            row = await cursor.fetchone()
        if row is None:
            await self.conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (1, utc_now_iso()),
            )
        await self.conn.commit()

    async def ping(self) -> bool:
        try:
            async with self.conn.execute("SELECT 1") as cursor:
                row = await cursor.fetchone()
            return row is not None
        except Exception:
            return False

    # --- Targets ---

    async def create_target(
        self,
        *,
        name: str,
        url: str,
        health_path: str = "/",
        mode: str = "external",
        interval_sec: int = 15,
        expected_git_sha: str | None = None,
        slo_max_p95_ms: float = 1000.0,
        slo_max_error_rate: float = 0.1,
        verify_window_sec: int = 60,
        rollback_type: str = "none",
        rollback_config: dict[str, Any] | None = None,
        alert_webhook_url: str | None = None,
    ) -> dict[str, Any]:
        target_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        config_json = json.dumps(rollback_config or {})
        await self.conn.execute(
            """
            INSERT INTO targets (
                id, name, url, health_path, mode, interval_sec, expected_git_sha,
                slo_max_p95_ms, slo_max_error_rate, verify_window_sec,
                rollback_type, rollback_config_json, alert_webhook_url, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'healthy', ?)
            """,
            (
                target_id,
                name,
                url,
                health_path,
                mode,
                interval_sec,
                expected_git_sha,
                slo_max_p95_ms,
                slo_max_error_rate,
                verify_window_sec,
                rollback_type,
                config_json,
                alert_webhook_url,
                created_at,
            ),
        )
        await self.conn.commit()
        target = await self.get_target(target_id)
        assert target is not None
        return target

    async def list_targets(self) -> list[dict[str, Any]]:
        async with self.conn.execute("SELECT * FROM targets ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
        return [self._decode_target(row) for row in rows]

    async def get_target(self, target_id: str) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM targets WHERE id = ?", (target_id,)) as cursor:
            row = await cursor.fetchone()
        return self._decode_target(row) if row is not None else None

    async def delete_target(self, target_id: str) -> bool:
        cursor = await self.conn.execute("DELETE FROM targets WHERE id = ?", (target_id,))
        await self.conn.commit()
        return cursor.rowcount > 0

    async def update_target_status(self, target_id: str, status: str) -> None:
        await self.conn.execute("UPDATE targets SET status = ? WHERE id = ?", (status, target_id))
        await self.conn.commit()

    async def update_target_expected_sha(self, target_id: str, expected_git_sha: str | None) -> None:
        await self.conn.execute(
            "UPDATE targets SET expected_git_sha = ? WHERE id = ?",
            (expected_git_sha, target_id),
        )
        await self.conn.commit()

    @staticmethod
    def _decode_target(row: aiosqlite.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["rollback_config"] = json.loads(data.get("rollback_config_json") or "{}")
        except json.JSONDecodeError:
            data["rollback_config"] = {}
        return data

    # --- Probe Results ---

    async def insert_probe_result(
        self,
        *,
        target_id: str,
        status_code: int | None,
        dns_ms: float | None,
        tls_ms: float | None,
        ttfb_ms: float | None,
        total_ms: float | None,
        tls_expiry_days: int | None,
        live_git_sha: str | None,
        headers_hash: str | None,
        error_msg: str | None,
        is_success: bool,
        checked_at: str | None = None,
    ) -> dict[str, Any]:
        ts = checked_at or utc_now_iso()
        cursor = await self.conn.execute(
            """
            INSERT INTO probe_results (
                target_id, status_code, dns_ms, tls_ms, ttfb_ms, total_ms,
                tls_expiry_days, live_git_sha, headers_hash, error_msg, is_success, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_id,
                status_code,
                dns_ms,
                tls_ms,
                ttfb_ms,
                total_ms,
                tls_expiry_days,
                live_git_sha,
                headers_hash,
                error_msg,
                1 if is_success else 0,
                ts,
            ),
        )
        await self.conn.commit()
        return {
            "id": cursor.lastrowid,
            "target_id": target_id,
            "status_code": status_code,
            "dns_ms": dns_ms,
            "tls_ms": tls_ms,
            "ttfb_ms": ttfb_ms,
            "total_ms": total_ms,
            "tls_expiry_days": tls_expiry_days,
            "live_git_sha": live_git_sha,
            "headers_hash": headers_hash,
            "error_msg": error_msg,
            "is_success": is_success,
            "checked_at": ts,
        }

    async def get_recent_probes(self, target_id: str, limit: int = 60) -> list[dict[str, Any]]:
        async with self.conn.execute(
            """
            SELECT * FROM probe_results
            WHERE target_id = ?
            ORDER BY checked_at DESC, id DESC
            LIMIT ?
            """,
            (target_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["is_success"] = bool(item["is_success"])
            results.append(item)
        return results

    async def get_baseline_headers_hash(self, target_id: str) -> str | None:
        async with self.conn.execute(
            """
            SELECT headers_hash FROM probe_results
            WHERE target_id = ? AND is_success = 1 AND headers_hash IS NOT NULL
            ORDER BY checked_at ASC, id ASC
            LIMIT 1
            """,
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return str(row["headers_hash"]) if row is not None else None

    async def prune_old_probes(self, retention_hours: int = 24) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).isoformat()
        cursor = await self.conn.execute("DELETE FROM probe_results WHERE checked_at < ?", (cutoff,))
        await self.conn.commit()
        return cursor.rowcount

    # --- Deployments ---

    async def create_deployment(
        self,
        *,
        target_id: str,
        commit_sha: str,
        image_tag: str,
        previous_image_tag: str | None = None,
        state: str = "verifying",
        summary: str | None = None,
    ) -> dict[str, Any]:
        deployment_id = str(uuid.uuid4())
        started_at = utc_now_iso()
        await self.conn.execute(
            """
            INSERT INTO deployments (
                id, target_id, commit_sha, image_tag, previous_image_tag,
                state, started_at, completed_at, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                deployment_id,
                target_id,
                commit_sha,
                image_tag,
                previous_image_tag,
                state,
                started_at,
                summary,
            ),
        )
        await self.conn.commit()
        deployment = await self.get_deployment(deployment_id)
        assert deployment is not None
        return deployment

    async def get_deployment(self, deployment_id: str) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def list_deployments(self, target_id: str, limit: int = 30) -> list[dict[str, Any]]:
        async with self.conn.execute(
            """
            SELECT * FROM deployments
            WHERE target_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (target_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_active_deployment(self, target_id: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            """
            SELECT * FROM deployments
            WHERE target_id = ? AND state = 'verifying'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def update_deployment(
        self,
        deployment_id: str,
        *,
        state: str,
        summary: str | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any] | None:
        done_ts = completed_at if completed_at is not None else utc_now_iso()
        await self.conn.execute(
            """
            UPDATE deployments
            SET state = ?, summary = ?, completed_at = ?
            WHERE id = ?
            """,
            (state, summary, done_ts, deployment_id),
        )
        await self.conn.commit()
        return await self.get_deployment(deployment_id)

    # --- Incidents ---

    async def create_incident(
        self,
        *,
        target_id: str,
        trigger_reason: str,
        deployment_id: str | None = None,
        offending_sha: str | None = None,
        metrics_snapshot: dict[str, Any] | None = None,
        rollback_executed: bool = False,
        rollback_output: str | None = None,
    ) -> dict[str, Any]:
        incident_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        await self.conn.execute(
            """
            INSERT INTO incidents (
                id, target_id, deployment_id, trigger_reason, offending_sha,
                metrics_snapshot_json, rollback_executed, rollback_output, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                incident_id,
                target_id,
                deployment_id,
                trigger_reason,
                offending_sha,
                json.dumps(metrics_snapshot or {}),
                1 if rollback_executed else 0,
                rollback_output,
                created_at,
            ),
        )
        await self.conn.commit()
        incident = await self.get_incident(incident_id)
        assert incident is not None
        return incident

    async def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            """
            SELECT i.*, t.name AS target_name
            FROM incidents i
            LEFT JOIN targets t ON t.id = i.target_id
            WHERE i.id = ?
            """,
            (incident_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._decode_incident(row) if row is not None else None

    async def get_open_incident(self, target_id: str, trigger_reason: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            """
            SELECT i.*, t.name AS target_name
            FROM incidents i
            LEFT JOIN targets t ON t.id = i.target_id
            WHERE i.target_id = ? AND i.trigger_reason = ? AND i.resolved_at IS NULL
            ORDER BY i.created_at DESC
            LIMIT 1
            """,
            (target_id, trigger_reason),
        ) as cursor:
            row = await cursor.fetchone()
        return self._decode_incident(row) if row is not None else None

    async def resolve_open_incidents(self, target_id: str, reasons: list[str] | None = None) -> int:
        now = utc_now_iso()
        if reasons:
            placeholders = ",".join("?" for _ in reasons)
            cursor = await self.conn.execute(
                f"""
                UPDATE incidents
                SET resolved_at = ?
                WHERE target_id = ? AND resolved_at IS NULL AND trigger_reason IN ({placeholders})
                """,
                (now, target_id, *reasons),
            )
        else:
            cursor = await self.conn.execute(
                "UPDATE incidents SET resolved_at = ? WHERE target_id = ? AND resolved_at IS NULL",
                (now, target_id),
            )
        await self.conn.commit()
        return cursor.rowcount

    async def list_incidents(self, target_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if target_id:
            async with self.conn.execute(
                """
                SELECT i.*, t.name AS target_name
                FROM incidents i
                LEFT JOIN targets t ON t.id = i.target_id
                WHERE i.target_id = ?
                ORDER BY i.created_at DESC
                LIMIT ?
                """,
                (target_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with self.conn.execute(
                """
                SELECT i.*, t.name AS target_name
                FROM incidents i
                LEFT JOIN targets t ON t.id = i.target_id
                ORDER BY i.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._decode_incident(row) for row in rows]

    @staticmethod
    def _decode_incident(row: aiosqlite.Row) -> dict[str, Any]:
        data = dict(row)
        data["rollback_executed"] = bool(data.get("rollback_executed"))
        try:
            data["metrics_snapshot"] = json.loads(data.get("metrics_snapshot_json") or "{}")
        except json.JSONDecodeError:
            data["metrics_snapshot"] = {}
        return data
