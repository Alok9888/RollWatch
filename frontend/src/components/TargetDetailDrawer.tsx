"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  GitCommitHorizontal,
  Lock,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Deployment, ProbeResult, RollbackExecutionResult, Target } from "@/types/rollwatch";
import { DeploymentStateBadge, ModeBadge, StatusPill } from "./StatusBadge";

interface TargetDetailDrawerProps {
  target: Target | null;
  onClose: () => void;
  onDataChanged: () => void;
}

function formatClock(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function TargetDetailDrawer({ target, onClose, onDataChanged }: TargetDetailDrawerProps) {
  const [probes, setProbes] = useState<ProbeResult[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [checking, setChecking] = useState(false);
  const [rollingBack, setRollingBack] = useState(false);
  const [rollbackTagInput, setRollbackTagInput] = useState("");
  const [rollbackResult, setRollbackResult] = useState<RollbackExecutionResult | null>(null);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const fetchDetails = useCallback(async () => {
    if (!target) return;
    try {
      const [probeData, depData] = await Promise.all([
        api.getProbes(target.id, 60),
        api.getDeployments(target.id),
      ]);
      setProbes(probeData);
      setDeployments(depData);
    } catch {
      // Errors handled gracefully during polling
    }
  }, [target]);

  useEffect(() => {
    if (!target) return;
    setRollbackResult(null);
    setRollbackError(null);
    setRollbackTagInput("");
    fetchDetails();

    const poll = setInterval(fetchDetails, 4000);
    const ticker = setInterval(() => setNowMs(Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(ticker);
    };
  }, [target, fetchDetails]);

  useEffect(() => {
    if (!target) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [target, onClose]);

  const chartData = useMemo(() => {
    return [...probes]
      .reverse()
      .map((p) => ({
        time: formatClock(p.checked_at),
        ttfb_ms: p.ttfb_ms ?? 0,
        total_ms: p.total_ms ?? 0,
        dns_ms: p.dns_ms ?? 0,
        tls_ms: p.tls_ms ?? 0,
        status_code: p.status_code,
        is_success: p.is_success,
      }));
  }, [probes]);

  if (!target) return null;

  const latestProbe = probes[0] ?? null;
  const activeDeployment = deployments.find((d) => d.state === "verifying") ?? target.active_deployment;

  let verifyProgressPct = 0;
  let verifyRemainingSec = 0;
  if (activeDeployment) {
    const startedMs = new Date(activeDeployment.started_at).getTime();
    const elapsedSec = Math.max(0, (nowMs - startedMs) / 1000);
    verifyProgressPct = Math.min(100, Math.round((elapsedSec / target.verify_window_sec) * 100));
    verifyRemainingSec = Math.max(0, Math.ceil(target.verify_window_sec - elapsedSec));
  }

  const handleCheckNow = async () => {
    setChecking(true);
    try {
      await api.checkNow(target.id);
      await fetchDetails();
      onDataChanged();
    } finally {
      setChecking(false);
    }
  };

  const handleRollback = async () => {
    setRollingBack(true);
    setRollbackError(null);
    setRollbackResult(null);
    try {
      const res = await api.triggerRollback(target.id, rollbackTagInput.trim() || undefined);
      setRollbackResult(res);
      await fetchDetails();
      onDataChanged();
    } catch (err) {
      setRollbackError(err instanceof Error ? err.message : "Rollback failed");
    } finally {
      setRollingBack(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/65 backdrop-blur-[2px]" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-2xl flex-col border-l border-slate-800 bg-[#0b0e14] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-800 px-6 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-lg font-semibold text-slate-100">{target.name}</h2>
              <ModeBadge mode={target.mode} />
              <StatusPill status={target.status} />
            </div>
            <div className="mt-1 font-mono text-xs text-slate-400">
              {target.url}
              {target.health_path !== "/" ? target.health_path : ""}
            </div>
          </div>

          <div className="ml-3 flex items-center gap-2">
            <button
              type="button"
              disabled={checking}
              onClick={handleCheckNow}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-sky-500/50 hover:text-sky-200 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${checking ? "animate-spin text-sky-400" : ""}`} />
              Probe Now
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 space-y-5 overflow-y-auto p-6">
          {/* Live network breakdown strip */}
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-6">
            {[
              { label: "DNS", value: latestProbe?.dns_ms != null ? `${latestProbe.dns_ms.toFixed(0)}ms` : "—" },
              { label: "TLS", value: latestProbe?.tls_ms != null ? `${latestProbe.tls_ms.toFixed(0)}ms` : "—" },
              { label: "TTFB", value: latestProbe?.ttfb_ms != null ? `${latestProbe.ttfb_ms.toFixed(0)}ms` : "—" },
              { label: "Total", value: latestProbe?.total_ms != null ? `${latestProbe.total_ms.toFixed(0)}ms` : "—" },
              {
                label: "p95",
                value: target.current_p95_ms != null ? `${target.current_p95_ms.toFixed(0)}ms` : "—",
                warn: target.current_p95_ms != null && target.current_p95_ms > target.slo_max_p95_ms,
              },
              {
                label: "HTTP",
                value: latestProbe?.status_code != null ? String(latestProbe.status_code) : "ERR",
                warn: latestProbe != null && !latestProbe.is_success,
              },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-lg border border-slate-800/90 bg-[#0f131b] px-3 py-2 text-center"
              >
                <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
                  {item.label}
                </div>
                <div
                  className={`mt-0.5 font-mono text-sm font-semibold ${
                    item.warn ? "text-rose-400" : "text-slate-100"
                  }`}
                >
                  {item.value}
                </div>
              </div>
            ))}
          </div>

          {/* Latency chart */}
          <div className="rounded-lg border border-slate-800/90 bg-[#0f131b] p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                  Latency Breakdown (TTFB & Total ms)
                </h3>
                <p className="text-[11px] text-slate-500">
                  Last {chartData.length} real probes · Red dashed line = SLO p95 limit ({target.slo_max_p95_ms}ms)
                </p>
              </div>
              <div className="flex items-center gap-3 text-[11px] text-slate-400">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-sky-400" /> Total
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-emerald-400" /> TTFB
                </span>
              </div>
            </div>

            {chartData.length > 0 ? (
              <div className="h-56 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                    <defs>
                      <linearGradient id="totalGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.28} />
                        <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
                      </linearGradient>
                      <linearGradient id="ttfbGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.28} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis
                      dataKey="time"
                      tick={{ fill: "#64748b", fontSize: 10 }}
                      axisLine={{ stroke: "#1e293b" }}
                      tickLine={false}
                      minTickGap={24}
                    />
                    <YAxis
                      tick={{ fill: "#64748b", fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                      unit="ms"
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#0f131b",
                        border: "1px solid #334155",
                        borderRadius: "8px",
                        fontSize: "12px",
                        fontFamily: "var(--font-mono)",
                      }}
                    />
                    <ReferenceLine
                      y={target.slo_max_p95_ms}
                      stroke="#f43f5e"
                      strokeDasharray="5 5"
                      strokeWidth={1.5}
                    />
                    <Area
                      type="monotone"
                      dataKey="total_ms"
                      name="Total (ms)"
                      stroke="#38bdf8"
                      strokeWidth={2}
                      fill="url(#totalGrad)"
                      isAnimationActive={false}
                    />
                    <Area
                      type="monotone"
                      dataKey="ttfb_ms"
                      name="TTFB (ms)"
                      stroke="#10b981"
                      strokeWidth={1.75}
                      fill="url(#ttfbGrad)"
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-44 items-center justify-center text-xs text-slate-500">
                Waiting for first probe measurement...
              </div>
            )}
          </div>

          {/* TLS Certificate & Header Drift cards */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-slate-800/90 bg-[#0f131b] p-4">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
                <Lock className="h-3.5 w-3.5 text-sky-400" />
                TLS Certificate
              </div>
              {target.url.startsWith("https://") ? (
                <div className="mt-2.5 space-y-1">
                  <div className="font-mono text-lg font-semibold text-slate-100">
                    {target.tls_expiry_days !== null ? `${target.tls_expiry_days} days left` : "Inspecting..."}
                  </div>
                  <div className="text-xs text-slate-400">
                    {target.tls_expiry_days !== null && target.tls_expiry_days <= 14
                      ? "Certificate expiring soon — renew immediately"
                      : "Valid TLS chain verified via live handshake"}
                  </div>
                </div>
              ) : (
                <div className="mt-2.5 text-xs text-slate-500">
                  Plain HTTP endpoint — TLS check gracefully skipped.
                </div>
              )}
            </div>

            <div className="rounded-lg border border-slate-800/90 bg-[#0f131b] p-4">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
                  {target.header_drift ? (
                    <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                  )}
                  Header Drift
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                    target.header_drift
                      ? "bg-amber-500/15 text-amber-300"
                      : "bg-emerald-500/10 text-emerald-300"
                  }`}
                >
                  {target.header_drift ? "Drifted" : "Stable"}
                </span>
              </div>
              <div className="mt-2.5 space-y-1 font-mono text-[11px] text-slate-400">
                <div>Base: {target.baseline_headers_hash ? target.baseline_headers_hash.slice(0, 14) : "—"}</div>
                <div>Live: {target.latest_headers_hash ? target.latest_headers_hash.slice(0, 14) : "—"}</div>
              </div>
            </div>
          </div>

          {/* Deployments & Verification Timeline */}
          <div className="rounded-lg border border-slate-800/90 bg-[#0f131b] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                  Deployments & Verification Timeline
                </h3>
                <p className="text-[11px] text-slate-500">
                  Adapter: <span className="font-mono text-slate-300">{target.rollback_type}</span> · Target ID:{" "}
                  <span className="font-mono text-slate-400">{target.id.slice(0, 8)}</span>
                </p>
              </div>
            </div>

            {/* Active Verification Countdown */}
            {activeDeployment && (
              <div className="mt-3 rounded-lg border border-sky-500/35 bg-sky-500/10 p-3.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 font-medium text-sky-200">
                    <Clock className="h-3.5 w-3.5 animate-pulse text-sky-400" />
                    Verifying release{" "}
                    <span className="font-mono text-sky-100">{activeDeployment.image_tag}</span> (
                    {activeDeployment.commit_sha.slice(0, 7)})
                  </span>
                  <span className="font-mono text-sky-300">{verifyRemainingSec}s left</span>
                </div>
                <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-900">
                  <div
                    className="h-full rounded-full bg-sky-400 transition-all duration-700"
                    style={{ width: `${verifyProgressPct}%` }}
                  />
                </div>
                <div className="mt-1.5 flex justify-between text-[11px] text-sky-300/80">
                  <span>Probing every 5s against p95 &le; {target.slo_max_p95_ms}ms</span>
                  <span>{verifyProgressPct}%</span>
                </div>
              </div>
            )}

            {/* Manual Rollback Control */}
            <div className="mt-3 flex flex-col gap-2 rounded-lg border border-slate-800 bg-[#0b0e14] p-3 sm:flex-row sm:items-center">
              <input
                value={rollbackTagInput}
                onChange={(e) => setRollbackTagInput(e.target.value)}
                placeholder="Optional image tag (defaults to previous tag)"
                className="flex-1 rounded-md border border-slate-700 bg-[#090b10] px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-rose-500 focus:outline-none"
              />
              <button
                type="button"
                disabled={rollingBack}
                onClick={handleRollback}
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-rose-500/50 bg-rose-500/15 px-3.5 py-1.5 text-xs font-semibold text-rose-200 transition-colors hover:bg-rose-500/25 disabled:opacity-50"
              >
                <RotateCcw className={`h-3.5 w-3.5 ${rollingBack ? "animate-spin" : ""}`} />
                {rollingBack ? "Rolling Back..." : "Rollback Now"}
              </button>
            </div>

            {rollbackError && (
              <div className="mt-2 rounded border border-rose-500/40 bg-rose-500/10 p-2.5 text-xs text-rose-300">
                {rollbackError}
              </div>
            )}

            {rollbackResult && (
              <div className="mt-2.5 rounded-md border border-amber-500/35 bg-black/50 p-3 font-mono text-[11px] text-amber-200">
                <div className="flex items-center justify-between text-xs font-semibold">
                  <span>
                    Rollback ({rollbackResult.adapter}
                    {rollbackResult.dry_run ? " · DRY-RUN" : ""})
                  </span>
                  <span>{rollbackResult.success ? "OK" : "FAILED"}</span>
                </div>
                <pre className="mt-1.5 whitespace-pre-wrap break-all text-slate-300">{rollbackResult.output}</pre>
              </div>
            )}

            {/* Deployment History */}
            <div className="mt-4 space-y-2">
              {deployments.length === 0 ? (
                <div className="rounded-md border border-dashed border-slate-800 p-4 text-center text-xs text-slate-500">
                  No deployments recorded yet. Send a POST to <code className="text-slate-300">/api/webhooks/deploy</code>{" "}
                  from GitHub Actions to trigger automated post-deploy verification.
                </div>
              ) : (
                deployments.map((dep) => (
                  <div
                    key={dep.id}
                    className="rounded-md border border-slate-800/90 bg-[#0b0e14] px-3.5 py-2.5 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <DeploymentStateBadge state={dep.state} />
                        <span className="inline-flex items-center gap-1 font-mono text-slate-200">
                          <GitCommitHorizontal className="h-3.5 w-3.5 text-slate-400" />
                          {dep.commit_sha.slice(0, 7)}
                        </span>
                        <span className="font-mono text-slate-400">{dep.image_tag}</span>
                      </div>
                      <span className="font-mono text-[11px] text-slate-500">
                        {new Date(dep.started_at).toLocaleString()}
                      </span>
                    </div>
                    {dep.summary && <p className="mt-1.5 text-[11px] text-slate-400">{dep.summary}</p>}
                  </div>
                ))
              )}
            </div>
          </div>

          {latestProbe?.error_msg && (
            <div className="flex items-start gap-2 rounded-lg border border-rose-500/35 bg-rose-500/10 p-3 text-xs text-rose-200">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
              <div>
                <div className="font-semibold">Latest Probe Error</div>
                <div className="mt-0.5 font-mono text-[11px] text-rose-300">{latestProbe.error_msg}</div>
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
