from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from app.config import Settings
from app.rollback import (
    AwsSsmRollbackExecutor,
    GitHubDispatchRollbackExecutor,
    RollbackContext,
    WebhookRollbackExecutor,
)


@pytest.mark.asyncio
async def test_aws_ssm_falls_back_to_dry_run_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setattr(AwsSsmRollbackExecutor, "_has_aws_credentials", staticmethod(lambda _r: False))

    executor = AwsSsmRollbackExecutor(Settings())
    result = await executor.execute(
        RollbackContext(
            target_id="t-1",
            target_name="trace",
            failed_sha="abc1234",
            rollback_to_tag="123456789012.dkr.ecr.us-east-1.amazonaws.com/trace:v1",
            config={"instance_id": "i-0abc123", "container_name": "trace-api", "region": "us-east-1"},
        )
    )
    assert result.executed is True
    assert result.dry_run is True
    assert result.success is True
    assert "[DRY-RUN]" in result.output
    assert "docker pull" in result.output


@pytest.mark.asyncio
async def test_aws_ssm_executes_real_ssm_send_command_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send_command(
        self: AwsSsmRollbackExecutor,
        *,
        region: str,
        instance_id: str,
        commands: list[str],
        comment: str,
    ) -> dict[str, Any]:
        captured["region"] = region
        captured["instance_id"] = instance_id
        captured["commands"] = commands
        captured["comment"] = comment
        return {"Command": {"CommandId": "ssm-cmd-999", "Status": "Pending"}}

    monkeypatch.setattr(AwsSsmRollbackExecutor, "_has_aws_credentials", staticmethod(lambda _r: True))
    monkeypatch.setattr(AwsSsmRollbackExecutor, "_send_ssm_command_sync", fake_send_command)

    executor = AwsSsmRollbackExecutor(Settings())
    result = await executor.execute(
        RollbackContext(
            target_id="t-1",
            target_name="trace",
            failed_sha="abc1234",
            rollback_to_tag="v1.4.2",
            config={
                "instance_id": "i-0abc123",
                "region": "ap-south-1",
                "ecr_repo": "111122223333.dkr.ecr.ap-south-1.amazonaws.com/trace",
                "container_name": "trace",
            },
        )
    )
    assert result.dry_run is False
    assert result.success is True
    assert result.command_id == "ssm-cmd-999"
    assert captured["region"] == "ap-south-1"
    assert captured["instance_id"] == "i-0abc123"
    assert any("aws ecr get-login-password" in cmd for cmd in captured["commands"])
    assert any("trace:v1.4.2" in cmd for cmd in captured["commands"])


@pytest.mark.asyncio
async def test_github_dispatch_dry_run_without_token() -> None:
    executor = GitHubDispatchRollbackExecutor(Settings(github_token=None))
    result = await executor.execute(
        RollbackContext(
            target_id="t-2",
            target_name="billing",
            failed_sha="1122334",
            rollback_to_tag="v2.0.0",
            config={"owner": "acme", "repo": "billing", "workflow": "rollback.yml"},
        )
    )
    assert result.dry_run is True
    assert result.success is True
    assert "GITHUB_TOKEN" in result.output


def test_webhook_hmac_signature_matches_sha256() -> None:
    body = b'{"target_id":"123","rollback_to_tag":"v1"}'
    secret = "super-secret"
    sig = WebhookRollbackExecutor.sign_payload(body, secret)
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sig == expected
