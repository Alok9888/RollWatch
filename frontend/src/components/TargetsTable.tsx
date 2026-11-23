"use client";

import { ExternalLink, GitCommitHorizontal, Lock, RefreshCw, Trash2 } from "lucide-react";
import type { Target } from "@/types/rollwatch";
import { ModeBadge, StatusPill } from "./StatusBadge";

interface TargetsTableProps {
  targets: Target[];
  checkingIds: Record<string, boolean>;
  onSelect: (target: Target) => void;
  onCheckNow: (targetId: string) => void;
  onDelete: (targetId: string) => void;
}

function formatSslDays(days: number | null, url: string) {
  if (!url.startsWith("https://")) {
    return <span className="font-mono text-xs text-slate-500">HTTP</span>;
  }
  if (days === null) {
    return <span className="font-mono text-xs text-slate-500">—</span>;
  }
  const color = days <= 14 ? "text-rose-400" : days <= 30 ? "text-amber-300" : "text-emerald-400";
  return (
    <span className={`inline-flex items-center gap-1 font-mono text-xs ${color}`}>
      <Lock className="h-3 w-3 opacity-80" />
      {days}d
    </span>
  );
}

export function TargetsTable({
  targets,
  checkingIds,
  onSelect,
  onCheckNow,
  onDelete,
}: TargetsTableProps) {
  if (targets.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-800 bg-[#0f131b]/70 p-12 text-center">
        <p className="text-sm font-medium text-slate-200">No targets monitored yet</p>
        <p className="mt-1 text-xs text-slate-400">
          Add any live public URL or register a managed service with SLO verification and auto-rollback.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-800/90 bg-[#0f131b]">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-slate-800/90 bg-[#0c1017] text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Target</th>
              <th className="px-4 py-3">Mode</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">p95 Latency</th>
              <th className="px-4 py-3 text-right">SSL Expiry</th>
              <th className="px-4 py-3">Live Git SHA</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70 text-sm">
            {targets.map((target) => {
              const isChecking = Boolean(checkingIds[target.id]);
              const p95OverSlo =
                target.current_p95_ms !== null && target.current_p95_ms > target.slo_max_p95_ms;
              const shortSha = target.live_git_sha ? target.live_git_sha.slice(0, 7) : null;

              return (
                <tr
                  key={target.id}
                  onClick={() => onSelect(target)}
                  className="group cursor-pointer transition-colors hover:bg-[#141a25]"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-100 group-hover:text-sky-300">
                        {target.name}
                      </span>
                      {target.header_drift && (
                        <span className="rounded border border-amber-500/35 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                          HDR DRIFT
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5 font-mono text-xs text-slate-500">
                      <span className="max-w-[280px] truncate">
                        {target.url}
                        {target.health_path !== "/" ? target.health_path : ""}
                      </span>
                      <ExternalLink className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-60" />
                    </div>
                  </td>

                  <td className="px-4 py-3">
                    <ModeBadge mode={target.mode} />
                  </td>

                  <td className="px-4 py-3">
                    <StatusPill status={target.status} />
                  </td>

                  <td className="px-4 py-3 text-right font-mono text-xs">
                    {target.current_p95_ms !== null ? (
                      <span className={p95OverSlo ? "font-semibold text-rose-400" : "text-slate-200"}>
                        {target.current_p95_ms.toFixed(0)} ms
                      </span>
                    ) : (
                      <span className="text-slate-500">—</span>
                    )}
                    <div className="text-[10px] text-slate-500">SLO {target.slo_max_p95_ms}ms</div>
                  </td>

                  <td className="px-4 py-3 text-right">{formatSslDays(target.tls_expiry_days, target.url)}</td>

                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {shortSha ? (
                        <span className="inline-flex items-center gap-1 rounded bg-slate-900 px-2 py-0.5 font-mono text-xs text-slate-200 ring-1 ring-slate-800">
                          <GitCommitHorizontal className="h-3 w-3 text-slate-400" />
                          {shortSha}
                        </span>
                      ) : (
                        <span className="font-mono text-xs text-slate-500">
                          {target.mode === "managed" ? "awaiting" : "n/a"}
                        </span>
                      )}
                      {target.version_drift && (
                        <span className="rounded border border-rose-500/50 bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-rose-300">
                          DRIFT
                        </span>
                      )}
                    </div>
                    {target.version_drift && target.expected_git_sha && (
                      <div className="mt-0.5 font-mono text-[10px] text-rose-400/90">
                        expected {target.expected_git_sha.slice(0, 7)}
                      </div>
                    )}
                  </td>

                  <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="inline-flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={isChecking}
                        onClick={() => onCheckNow(target.id)}
                        className="inline-flex items-center gap-1.5 rounded-md border border-slate-700/90 bg-slate-900 px-2.5 py-1 text-xs font-medium text-slate-200 transition-colors hover:border-sky-500/50 hover:bg-slate-800 hover:text-sky-200 disabled:opacity-50"
                      >
                        <RefreshCw className={`h-3 w-3 ${isChecking ? "animate-spin text-sky-400" : ""}`} />
                        Check Now
                      </button>
                      <button
                        type="button"
                        title="Delete target"
                        onClick={() => onDelete(target.id)}
                        className="rounded-md border border-transparent p-1.5 text-slate-500 transition-colors hover:border-rose-500/30 hover:bg-rose-500/10 hover:text-rose-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
