"use client";

import { useState } from "react";
import { Globe, Server, X } from "lucide-react";
import type { RollbackType, TargetCreatePayload } from "@/types/rollwatch";

interface AddTargetModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: TargetCreatePayload) => Promise<void>;
}

export function AddTargetModal({ open, onClose, onSubmit }: AddTargetModalProps) {
  const [tab, setTab] = useState<"external" | "managed">("external");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Common fields
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [alertWebhookUrl, setAlertWebhookUrl] = useState("");
  const [intervalSec, setIntervalSec] = useState("15");

  // Managed fields
  const [healthPath, setHealthPath] = useState("/health");
  const [expectedGitSha, setExpectedGitSha] = useState("");
  const [sloMaxP95Ms, setSloMaxP95Ms] = useState("500");
  const [sloMaxErrorRate, setSloMaxErrorRate] = useState("0.1");
  const [verifyWindowSec, setVerifyWindowSec] = useState("60");
  const [rollbackType, setRollbackType] = useState<RollbackType>("aws_ssm");

  // Rollback adapter config fields
  const [ssmInstanceId, setSsmInstanceId] = useState("");
  const [ssmRegion, setSsmRegion] = useState("us-east-1");
  const [ssmEcrRepo, setSsmEcrRepo] = useState("");
  const [ssmContainerName, setSsmContainerName] = useState("");
  const [ssmPortMapping, setSsmPortMapping] = useState("8080:8080");

  const [ghOwner, setGhOwner] = useState("");
  const [ghRepo, setGhRepo] = useState("");
  const [ghWorkflow, setGhWorkflow] = useState("rollback.yml");
  const [ghRef, setGhRef] = useState("main");

  const [hookUrl, setHookUrl] = useState("");
  const [hookSecret, setHookSecret] = useState("");

  if (!open) return null;

  const resetForm = () => {
    setName("");
    setUrl("");
    setAlertWebhookUrl("");
    setIntervalSec("15");
    setHealthPath("/health");
    setExpectedGitSha("");
    setSloMaxP95Ms("500");
    setSloMaxErrorRate("0.1");
    setVerifyWindowSec("60");
    setRollbackType("aws_ssm");
    setSsmInstanceId("");
    setSsmEcrRepo("");
    setSsmContainerName("");
    setGhOwner("");
    setGhRepo("");
    setHookUrl("");
    setHookSecret("");
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      let payload: TargetCreatePayload;
      if (tab === "external") {
        payload = {
          name: name.trim(),
          url: url.trim(),
          health_path: "/",
          mode: "external",
          interval_sec: Math.max(5, Number(intervalSec) || 15),
          alert_webhook_url: alertWebhookUrl.trim() || null,
          rollback_type: "none",
          rollback_config: {},
        };
      } else {
        let rollbackConfig: Record<string, string> = {};
        if (rollbackType === "aws_ssm") {
          rollbackConfig = {
            instance_id: ssmInstanceId.trim(),
            region: ssmRegion.trim() || "us-east-1",
            ecr_repo: ssmEcrRepo.trim(),
            container_name: ssmContainerName.trim(),
            port_mapping: ssmPortMapping.trim() || "8080:8080",
          };
        } else if (rollbackType === "github_dispatch") {
          rollbackConfig = {
            owner: ghOwner.trim(),
            repo: ghRepo.trim(),
            workflow: ghWorkflow.trim() || "rollback.yml",
            ref: ghRef.trim() || "main",
          };
        } else if (rollbackType === "webhook") {
          rollbackConfig = {
            url: hookUrl.trim(),
            ...(hookSecret.trim() ? { secret: hookSecret.trim() } : {}),
          };
        }

        payload = {
          name: name.trim(),
          url: url.trim(),
          health_path: healthPath.trim() || "/health",
          mode: "managed",
          interval_sec: Math.max(5, Number(intervalSec) || 15),
          expected_git_sha: expectedGitSha.trim() || null,
          slo_max_p95_ms: Number(sloMaxP95Ms) || 1000,
          slo_max_error_rate: Number(sloMaxErrorRate),
          verify_window_sec: Math.max(5, Number(verifyWindowSec) || 60),
          rollback_type: rollbackType,
          rollback_config: rollbackConfig,
          alert_webhook_url: alertWebhookUrl.trim() || null,
        };
      }

      await onSubmit(payload);
      resetForm();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create target");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-slate-800 bg-[#0f131b] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Add Monitored Target</h2>
            <p className="text-xs text-slate-400">
              Starts real outbound DNS, TLS, and HTTP probing immediately upon creation.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Mode tabs */}
        <div className="grid grid-cols-2 gap-2 border-b border-slate-800 bg-[#0b0e14] p-3">
          <button
            type="button"
            onClick={() => setTab("external")}
            className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
              tab === "external"
                ? "border-sky-500/50 bg-sky-500/15 text-sky-200"
                : "border-slate-800 bg-[#0f131b] text-slate-400 hover:text-slate-200"
            }`}
          >
            <Globe className="h-3.5 w-3.5" />
            Quick Public URL
          </button>
          <button
            type="button"
            onClick={() => setTab("managed")}
            className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
              tab === "managed"
                ? "border-violet-500/50 bg-violet-500/15 text-violet-200"
                : "border-slate-800 bg-[#0f131b] text-slate-400 hover:text-slate-200"
            }`}
          >
            <Server className="h-3.5 w-3.5" />
            Managed Service
          </button>
        </div>

        <form onSubmit={handleSubmit} className="max-h-[75vh] space-y-4 overflow-y-auto p-5">
          {error && (
            <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-slate-300">Service Name</label>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={tab === "external" ? "GitHub API" : "Trace Backend"}
                className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300">Probe Interval (sec)</label>
              <input
                type="number"
                min={5}
                max={3600}
                value={intervalSec}
                onChange={(e) => setIntervalSec(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-3 py-2 font-mono text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300">Target URL</label>
            <input
              required
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={tab === "external" ? "https://api.github.com" : "https://api.trace.example.com"}
              className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-3 py-2 font-mono text-sm text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
            />
          </div>

          {tab === "managed" && (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-medium text-slate-300">Health Path</label>
                  <input
                    value={healthPath}
                    onChange={(e) => setHealthPath(e.target.value)}
                    placeholder="/health"
                    className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-3 py-2 font-mono text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300">Expected Git SHA (optional)</label>
                  <input
                    value={expectedGitSha}
                    onChange={(e) => setExpectedGitSha(e.target.value)}
                    placeholder="a1b2c3d"
                    className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-3 py-2 font-mono text-sm text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                  />
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-[#0b0e14] p-3.5">
                <div className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Post-Deploy SLO Verification Thresholds
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[11px] text-slate-400">Max p95 (ms)</label>
                    <input
                      type="number"
                      min={10}
                      value={sloMaxP95Ms}
                      onChange={(e) => setSloMaxP95Ms(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-slate-400">Max Error Rate (0-1)</label>
                    <input
                      type="number"
                      step="0.01"
                      min={0}
                      max={1}
                      value={sloMaxErrorRate}
                      onChange={(e) => setSloMaxErrorRate(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-slate-400">Verify Window (s)</label>
                    <input
                      type="number"
                      min={5}
                      value={verifyWindowSec}
                      onChange={(e) => setVerifyWindowSec(e.target.value)}
                      className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-[#0b0e14] p-3.5 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Auto-Rollback Adapter
                  </span>
                  <select
                    value={rollbackType}
                    onChange={(e) => setRollbackType(e.target.value as RollbackType)}
                    className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1 text-xs text-slate-100 focus:border-sky-500 focus:outline-none"
                  >
                    <option value="aws_ssm">AWS SSM (EC2 / ECR)</option>
                    <option value="github_dispatch">GitHub Workflow Dispatch</option>
                    <option value="webhook">HMAC Webhook</option>
                    <option value="none">None (Alert Only)</option>
                  </select>
                </div>

                {rollbackType === "aws_ssm" && (
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    <input
                      value={ssmInstanceId}
                      onChange={(e) => setSsmInstanceId(e.target.value)}
                      placeholder="EC2 Instance ID (i-0abc123...)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={ssmRegion}
                      onChange={(e) => setSsmRegion(e.target.value)}
                      placeholder="AWS Region (us-east-1)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={ssmEcrRepo}
                      onChange={(e) => setSsmEcrRepo(e.target.value)}
                      placeholder="ECR Repo URI (123456.dkr.ecr.../trace)"
                      className="sm:col-span-2 rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={ssmContainerName}
                      onChange={(e) => setSsmContainerName(e.target.value)}
                      placeholder="Container Name (trace-api)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={ssmPortMapping}
                      onChange={(e) => setSsmPortMapping(e.target.value)}
                      placeholder="Port Mapping (8080:8080)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                )}

                {rollbackType === "github_dispatch" && (
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    <input
                      value={ghOwner}
                      onChange={(e) => setGhOwner(e.target.value)}
                      placeholder="GitHub Owner / Org"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={ghRepo}
                      onChange={(e) => setGhRepo(e.target.value)}
                      placeholder="Repository Name"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={ghWorkflow}
                      onChange={(e) => setGhWorkflow(e.target.value)}
                      placeholder="Workflow File (rollback.yml)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={ghRef}
                      onChange={(e) => setGhRef(e.target.value)}
                      placeholder="Git Ref (main)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                )}

                {rollbackType === "webhook" && (
                  <div className="grid grid-cols-1 gap-2.5">
                    <input
                      value={hookUrl}
                      onChange={(e) => setHookUrl(e.target.value)}
                      placeholder="Rollback Webhook URL (https://...)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                    <input
                      value={hookSecret}
                      onChange={(e) => setHookSecret(e.target.value)}
                      placeholder="HMAC Signing Secret (optional, defaults to ROLLWATCH_WEBHOOK_SECRET)"
                      className="rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
                    />
                  </div>
                )}
              </div>
            </>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-300">
              Alert Webhook URL <span className="text-slate-500">(Slack / Discord, optional)</span>
            </label>
            <input
              type="url"
              value={alertWebhookUrl}
              onChange={(e) => setAlertWebhookUrl(e.target.value)}
              placeholder="https://discord.com/api/webhooks/..."
              className="mt-1 w-full rounded-md border border-slate-700 bg-[#090b10] px-3 py-2 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-sky-500 focus:outline-none"
            />
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-slate-800 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-700 px-3.5 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 transition-colors hover:bg-sky-400 disabled:opacity-50"
            >
              {submitting ? "Adding..." : tab === "external" ? "Start Probing" : "Register Managed Service"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
