from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from app.config import Settings

logger = logging.getLogger("rollwatch.rollback")


@dataclass(frozen=True)
class RollbackContext:
    target_id: str
    target_name: str
    failed_sha: str | None
    rollback_to_tag: str
    config: dict[str, Any]


@dataclass(frozen=True)
class RollbackResult:
    adapter: str
    executed: bool
    dry_run: bool
    success: bool
    output: str
    command_id: str | None = None


class RollbackExecutor(ABC):
    """Abstract base class for pluggable RollWatch rollback adapters."""

    adapter_name: str

    @abstractmethod
    async def execute(self, context: RollbackContext) -> RollbackResult:
        """Execute a rollback to context.rollback_to_tag."""


class NoOpRollbackExecutor(RollbackExecutor):
    adapter_name = "none"

    async def execute(self, context: RollbackContext) -> RollbackResult:
        return RollbackResult(
            adapter=self.adapter_name,
            executed=False,
            dry_run=True,
            success=True,
            output=f"No rollback adapter configured for target {context.target_name}.",
        )


class AwsSsmRollbackExecutor(RollbackExecutor):
    adapter_name = "aws_ssm"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _build_shell_commands(context: RollbackContext, region: str) -> list[str]:
        cfg = context.config
        ecr_repo = str(cfg.get("ecr_repo") or "").strip()
        ecr_registry = str(cfg.get("ecr_registry") or "").strip()
        if not ecr_registry and "/" in ecr_repo:
            ecr_registry = ecr_repo.split("/", 1)[0]
        container_name = str(cfg.get("container_name") or context.target_name).strip()
        port_mapping = str(cfg.get("port_mapping") or "8080:8080").strip()
        env_file = str(cfg.get("env_file") or "").strip()

        image_ref = context.rollback_to_tag
        if ecr_repo and ":" not in image_ref and "/" not in image_ref:
            image_ref = f"{ecr_repo}:{image_ref}"

        q_region = shlex.quote(region)
        q_image = shlex.quote(image_ref)
        q_container = shlex.quote(container_name)
        q_port = shlex.quote(port_mapping)

        commands: list[str] = ["set -euo pipefail"]
        if ecr_registry:
            q_registry = shlex.quote(ecr_registry)
            commands.append(
                f"aws ecr get-login-password --region {q_region} | "
                f"docker login --username AWS --password-stdin {q_registry}"
            )
        commands.append(f"docker pull {q_image}")
        commands.append(f"docker stop {q_container} || true")
        commands.append(f"docker rm {q_container} || true")

        run_cmd = f"docker run -d --restart unless-stopped --name {q_container} -p {q_port}"
        if env_file:
            run_cmd += f" --env-file {shlex.quote(env_file)}"
        run_cmd += f" {q_image}"
        commands.append(run_cmd)
        commands.append(f"docker ps --filter name={q_container} --format '{{{{.Names}}}} {{{{.Image}}}} {{{{.Status}}}}'")
        return commands

    @staticmethod
    def _has_aws_credentials(region: str) -> bool:
        if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
            return True
        if os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI") or os.getenv("AWS_WEB_IDENTITY_TOKEN_FILE"):
            return True
        shared_creds = os.getenv("AWS_SHARED_CREDENTIALS_FILE") or os.path.expanduser("~/.aws/credentials")
        if os.path.isfile(shared_creds):
            return True
        if os.getenv("AWS_EC2_METADATA_ENABLED", "").lower() in {"1", "true", "yes"}:
            try:
                session = boto3.Session(region_name=region)
                return session.get_credentials() is not None
            except Exception:
                return False
        return False

    def _send_ssm_command_sync(
        self,
        *,
        region: str,
        instance_id: str,
        commands: list[str],
        comment: str,
    ) -> dict[str, Any]:
        client = boto3.client("ssm", region_name=region)
        return client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
            Comment=comment[:100],
        )

    async def execute(self, context: RollbackContext) -> RollbackResult:
        cfg = context.config
        instance_id = str(cfg.get("instance_id") or "").strip()
        region = str(cfg.get("region") or self.settings.aws_region).strip() or "us-east-1"
        commands = self._build_shell_commands(context, region)

        if not instance_id or not self._has_aws_credentials(region):
            missing: list[str] = []
            if not instance_id:
                missing.append("instance_id")
            if not self._has_aws_credentials(region):
                missing.append("AWS credentials")
            msg = (
                f"[DRY-RUN] AWS SSM skipped ({', '.join(missing)} not configured). "
                f"Would run AWS-RunShellScript in {region} on instance={instance_id or '<unset>'}:\n"
                + "\n".join(f"  $ {cmd}" for cmd in commands)
            )
            logger.info(msg)
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=True,
                success=True,
                output=msg,
            )

        comment = f"RollWatch rollback {context.target_name} -> {context.rollback_to_tag}"
        try:
            response = await asyncio.to_thread(
                self._send_ssm_command_sync,
                region=region,
                instance_id=instance_id,
                commands=commands,
                comment=comment,
            )
            command_meta = response.get("Command", {})
            command_id = command_meta.get("CommandId")
            status = command_meta.get("Status", "Pending")
            output = (
                f"AWS SSM AWS-RunShellScript dispatched to {instance_id} ({region}). "
                f"CommandId={command_id} Status={status}"
            )
            logger.info(output)
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=False,
                success=True,
                command_id=command_id,
                output=output,
            )
        except (NoCredentialsError, ClientError, BotoCoreError, Exception) as exc:
            error_output = f"AWS SSM rollback failed on {instance_id} ({region}): {exc}"
            logger.error(error_output)
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=False,
                success=False,
                output=error_output,
            )


class GitHubDispatchRollbackExecutor(RollbackExecutor):
    adapter_name = "github_dispatch"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(self, context: RollbackContext) -> RollbackResult:
        cfg = context.config
        owner = str(cfg.get("owner") or "").strip()
        repo = str(cfg.get("repo") or "").strip()
        workflow = str(cfg.get("workflow") or "").strip()
        ref = str(cfg.get("ref") or "main").strip() or "main"
        token = str(cfg.get("github_token") or self.settings.github_token or "").strip()

        endpoint = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
        payload = {
            "ref": ref,
            "inputs": {
                "previous_image_tag": context.rollback_to_tag,
                "failed_sha": context.failed_sha or "",
                "target_id": context.target_id,
            },
        }

        if not token or not owner or not repo or not workflow:
            missing = [
                field
                for field, value in (
                    ("GITHUB_TOKEN", token),
                    ("owner", owner),
                    ("repo", repo),
                    ("workflow", workflow),
                )
                if not value
            ]
            msg = (
                f"[DRY-RUN] GitHub workflow_dispatch skipped ({', '.join(missing)} not configured). "
                f"Would POST {endpoint} with payload={json.dumps(payload)}"
            )
            logger.info(msg)
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=True,
                success=True,
                output=msg,
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "RollWatch/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
            if response.status_code in (200, 201, 202, 204):
                output = (
                    f"GitHub Actions workflow_dispatch triggered: {owner}/{repo}@{ref} "
                    f"({workflow}) with previous_image_tag={context.rollback_to_tag} "
                    f"[HTTP {response.status_code}]"
                )
                return RollbackResult(
                    adapter=self.adapter_name,
                    executed=True,
                    dry_run=False,
                    success=True,
                    output=output,
                )
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=False,
                success=False,
                output=f"GitHub dispatch failed [HTTP {response.status_code}]: {response.text[:300]}",
            )
        except Exception as exc:
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=False,
                success=False,
                output=f"GitHub dispatch error: {exc}",
            )


class WebhookRollbackExecutor(RollbackExecutor):
    adapter_name = "webhook"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def sign_payload(body: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    async def execute(self, context: RollbackContext) -> RollbackResult:
        cfg = context.config
        url = str(cfg.get("url") or "").strip()
        secret = str(cfg.get("secret") or self.settings.webhook_secret).strip()

        payload = {
            "target_id": context.target_id,
            "target_name": context.target_name,
            "failed_sha": context.failed_sha,
            "rollback_to_tag": context.rollback_to_tag,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = self.sign_payload(raw_body, secret)

        if not url:
            msg = (
                f"[DRY-RUN] Webhook rollback skipped (url not configured). "
                f"Would POST payload={raw_body.decode('utf-8')} signature={signature}"
            )
            logger.info(msg)
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=True,
                success=True,
                output=msg,
            )

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "RollWatch/1.0",
            "X-RollWatch-Signature": signature,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, content=raw_body, headers=headers)
            if 200 <= response.status_code < 300:
                return RollbackResult(
                    adapter=self.adapter_name,
                    executed=True,
                    dry_run=False,
                    success=True,
                    output=f"Webhook rollback POST {url} succeeded [HTTP {response.status_code}]: {response.text[:250]}",
                )
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=False,
                success=False,
                output=f"Webhook rollback POST {url} failed [HTTP {response.status_code}]: {response.text[:250]}",
            )
        except Exception as exc:
            return RollbackResult(
                adapter=self.adapter_name,
                executed=True,
                dry_run=False,
                success=False,
                output=f"Webhook rollback error calling {url}: {exc}",
            )


def get_rollback_executor(rollback_type: str, settings: Settings) -> RollbackExecutor:
    if rollback_type == "aws_ssm":
        return AwsSsmRollbackExecutor(settings)
    if rollback_type == "github_dispatch":
        return GitHubDispatchRollbackExecutor(settings)
    if rollback_type == "webhook":
        return WebhookRollbackExecutor(settings)
    return NoOpRollbackExecutor()
