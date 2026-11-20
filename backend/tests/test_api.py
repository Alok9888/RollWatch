from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_full_api_lifecycle_and_retention(tmp_path: Path) -> None:
    db_file = tmp_path / "test_rollwatch.db"
    settings = Settings(
        db_path=str(db_file),
        webhook_secret="test-secret-123",
        git_sha="abc1234",
        enable_background_prober=False,
        verify_probe_interval_sec=0.05,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Health endpoint
            health_resp = await client.get("/health")
            assert health_resp.status_code == 200
            assert health_resp.json() == {"status": "ok", "git_sha": "abc1234", "db": "ok"}

            # 2. Metrics endpoint
            metrics_resp = await client.get("/metrics")
            assert metrics_resp.status_code == 200
            assert "rollwatch_target_up" in metrics_resp.text

            # 3. Create target
            create_resp = await client.post(
                "/api/targets",
                json={
                    "name": "Trace Backend",
                    "url": "https://trace.example.com",
                    "health_path": "/health",
                    "mode": "managed",
                    "expected_git_sha": "aaa1111",
                    "slo_max_p95_ms": 400,
                    "slo_max_error_rate": 0.1,
                    "verify_window_sec": 5,
                    "rollback_type": "aws_ssm",
                    "rollback_config": {"instance_id": "i-test", "container_name": "trace"},
                },
            )
            assert create_resp.status_code == 201
            created = create_resp.json()
            target_id = created["id"]
            assert created["name"] == "Trace Backend"
            assert created["mode"] == "managed"

            # 4. List & Get target
            list_resp = await client.get("/api/targets")
            assert list_resp.status_code == 200
            assert len(list_resp.json()) == 1

            get_resp = await client.get(f"/api/targets/{target_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["id"] == target_id

            # 5. Deploy webhook auth check
            unauth_resp = await client.post(
                "/api/webhooks/deploy",
                json={
                    "target_id": target_id,
                    "commit_sha": "bbb2222",
                    "image_tag": "trace:v2",
                    "previous_image_tag": "trace:v1",
                },
            )
            assert unauth_resp.status_code == 401

            # 6. Manual rollback (executes dry-run safely without AWS creds)
            rb_resp = await client.post(
                f"/api/targets/{target_id}/rollback",
                json={"rollback_to_tag": "trace:v1", "reason": "operator test"},
            )
            assert rb_resp.status_code == 200
            rb_data = rb_resp.json()
            assert rb_data["executed"] is True
            assert rb_data["rollback_to_tag"] == "trace:v1"

            # 7. Incidents list includes rollback incident
            inc_resp = await client.get("/api/incidents")
            assert inc_resp.status_code == 200
            incidents = inc_resp.json()
            assert len(incidents) == 1
            assert incidents[0]["rollback_executed"] is True

            # 8. Retention pruning keeps recent probes and removes >24h probes
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
            await app.state.db.insert_probe_result(
                target_id=target_id,
                status_code=200,
                dns_ms=1.0,
                tls_ms=2.0,
                ttfb_ms=10.0,
                total_ms=15.0,
                tls_expiry_days=60,
                live_git_sha="aaa1111",
                headers_hash="h1",
                error_msg=None,
                is_success=True,
                checked_at=old_ts,
            )
            await app.state.db.insert_probe_result(
                target_id=target_id,
                status_code=200,
                dns_ms=1.0,
                tls_ms=2.0,
                ttfb_ms=12.0,
                total_ms=18.0,
                tls_expiry_days=60,
                live_git_sha="aaa1111",
                headers_hash="h1",
                error_msg=None,
                is_success=True,
            )
            pruned = await app.state.db.prune_old_probes(24)
            assert pruned == 1
            probes_resp = await client.get(f"/api/targets/{target_id}/probes?limit=60")
            assert probes_resp.status_code == 200
            assert len(probes_resp.json()) == 1

            # 9. Delete target
            del_resp = await client.delete(f"/api/targets/{target_id}")
            assert del_resp.status_code == 204
            assert (await client.get(f"/api/targets/{target_id}")).status_code == 404
