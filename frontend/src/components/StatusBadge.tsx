"use client";

import type { DeploymentState, IncidentTrigger, TargetMode, TargetStatus } from "@/types/rollwatch";

const STATUS_STYLES: Record<TargetStatus, { dot: string; badge: string; label: string }> = {
  healthy: {
    dot: "bg-emerald-400",
    badge: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    label: "Healthy",
  },
  degraded: {
    dot: "bg-amber-400",
    badge: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    label: "Degraded",
  },
  down: {
    dot: "bg-rose-500",
    badge: "border-rose-500/40 bg-rose-500/15 text-rose-300",
    label: "Down",
  },
  verifying: {
    dot: "bg-sky-400 animate-pulse",
    badge: "border-sky-500/35 bg-sky-500/15 text-sky-300",
    label: "Verifying",
  },
  drifted: {
    dot: "bg-rose-400",
    badge: "border-rose-500/35 bg-rose-500/15 text-rose-300",
    label: "Drifted",
  },
};

export function StatusPill({ status }: { status: TargetStatus }) {
  const cfg = STATUS_STYLES[status] ?? STATUS_STYLES.healthy;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium tracking-tight ${cfg.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

export function ModeBadge({ mode }: { mode: TargetMode }) {
  if (mode === "managed") {
    return (
      <span className="inline-flex items-center rounded border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider text-violet-300">
        Managed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded border border-slate-700 bg-slate-800/70 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider text-slate-300">
      External
    </span>
  );
}

const DEPLOYMENT_STYLES: Record<DeploymentState, string> = {
  verifying: "border-sky-500/35 bg-sky-500/15 text-sky-300",
  verified: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  failed: "border-rose-500/40 bg-rose-500/15 text-rose-300",
  rolled_back: "border-amber-500/40 bg-amber-500/15 text-amber-300",
};

export function DeploymentStateBadge({ state }: { state: DeploymentState }) {
  const labels: Record<DeploymentState, string> = {
    verifying: "Verifying",
    verified: "Verified",
    failed: "Failed",
    rolled_back: "Rolled Back",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider ${DEPLOYMENT_STYLES[state]}`}
    >
      {labels[state]}
    </span>
  );
}

const TRIGGER_LABELS: Record<IncidentTrigger, { label: string; style: string }> = {
  slo_latency: {
    label: "SLO Latency Breach",
    style: "border-amber-500/35 bg-amber-500/10 text-amber-300",
  },
  slo_error_rate: {
    label: "SLO Error Rate",
    style: "border-rose-500/40 bg-rose-500/15 text-rose-300",
  },
  version_drift: {
    label: "Version Drift",
    style: "border-rose-500/40 bg-rose-500/15 text-rose-300",
  },
  tls_expiry: {
    label: "TLS Expiry",
    style: "border-amber-500/35 bg-amber-500/10 text-amber-300",
  },
  target_down: {
    label: "Target Down",
    style: "border-rose-500/40 bg-rose-500/15 text-rose-300",
  },
};

export function TriggerBadge({ reason }: { reason: IncidentTrigger }) {
  const cfg = TRIGGER_LABELS[reason];
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${cfg.style}`}>
      {cfg.label}
    </span>
  );
}
