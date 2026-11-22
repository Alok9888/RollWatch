export type TargetMode = "external" | "managed";
export type RollbackType = "none" | "aws_ssm" | "github_dispatch" | "webhook";
export type TargetStatus = "healthy" | "degraded" | "down" | "verifying" | "drifted";
export type DeploymentState = "verifying" | "verified" | "failed" | "rolled_back";
export type IncidentTrigger =
  | "slo_latency"
  | "slo_error_rate"
  | "version_drift"
  | "tls_expiry"
  | "target_down";

export interface Deployment {
  id: string;
  target_id: string;
  commit_sha: string;
  image_tag: string;
  previous_image_tag: string | null;
  state: DeploymentState;
  started_at: string;
  completed_at: string | null;
  summary: string | null;
}

export interface Target {
  id: string;
  name: string;
  url: string;
  health_path: string;
  mode: TargetMode;
  interval_sec: number;
  expected_git_sha: string | null;
  slo_max_p95_ms: number;
  slo_max_error_rate: number;
  verify_window_sec: number;
  rollback_type: RollbackType;
  rollback_config: Record<string, string>;
  alert_webhook_url: string | null;
  status: TargetStatus;
  created_at: string;
  current_p95_ms: number | null;
  current_error_rate: number | null;
  latest_total_ms: number | null;
  latest_ttfb_ms: number | null;
  latest_status_code: number | null;
  tls_expiry_days: number | null;
  live_git_sha: string | null;
  version_drift: boolean;
  header_drift: boolean;
  baseline_headers_hash: string | null;
  latest_headers_hash: string | null;
  last_checked_at: string | null;
  active_deployment: Deployment | null;
}

export interface TargetCreatePayload {
  name: string;
  url: string;
  health_path?: string;
  mode: TargetMode;
  interval_sec?: number;
  expected_git_sha?: string | null;
  slo_max_p95_ms?: number;
  slo_max_error_rate?: number;
  verify_window_sec?: number;
  rollback_type?: RollbackType;
  rollback_config?: Record<string, string>;
  alert_webhook_url?: string | null;
}

export interface ProbeResult {
  id: number;
  target_id: string;
  status_code: number | null;
  dns_ms: number | null;
  tls_ms: number | null;
  ttfb_ms: number | null;
  total_ms: number | null;
  tls_expiry_days: number | null;
  live_git_sha: string | null;
  headers_hash: string | null;
  error_msg: string | null;
  is_success: boolean;
  checked_at: string;
}

export interface Incident {
  id: string;
  target_id: string;
  target_name: string | null;
  deployment_id: string | null;
  trigger_reason: IncidentTrigger;
  offending_sha: string | null;
  metrics_snapshot: Record<string, unknown>;
  rollback_executed: boolean;
  rollback_output: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface RollbackExecutionResult {
  target_id: string;
  adapter: string;
  rollback_to_tag: string;
  executed: boolean;
  dry_run: boolean;
  success: boolean;
  command_id: string | null;
  output: string;
  incident_id: string | null;
}

export interface BackendHealth {
  status: "ok" | "degraded";
  git_sha: string;
  db: "ok" | "error";
}
