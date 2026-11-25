"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, GitCommitHorizontal, RotateCcw, Terminal } from "lucide-react";
import type { Incident } from "@/types/rollwatch";
import { TriggerBadge } from "./StatusBadge";

interface IncidentsViewProps {
  incidents: Incident[];
}

export function IncidentsView({ incidents }: IncidentsViewProps) {
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});

  const toggle = (id: string) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  if (incidents.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-800 bg-[#0f131b]/70 p-12 text-center">
        <p className="text-sm font-medium text-slate-200">No incidents recorded</p>
        <p className="mt-1 text-xs text-slate-400">
          SLO breaches, version drift alerts, TLS warnings, and automated rollbacks will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {incidents.map((incident) => {
        const isExpanded = Boolean(expandedIds[incident.id]);
        const snapshotEntries = Object.entries(incident.metrics_snapshot || {});

        return (
          <div
            key={incident.id}
            className="overflow-hidden rounded-lg border border-slate-800/90 bg-[#0f131b] transition-colors hover:border-slate-700"
          >
            <button
              type="button"
              onClick={() => toggle(incident.id)}
              className="flex w-full items-center justify-between gap-4 px-4 py-3.5 text-left"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2.5">
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
                )}
                <TriggerBadge reason={incident.trigger_reason} />
                <span className="font-medium text-slate-100">
                  {incident.target_name || incident.target_id.slice(0, 8)}
                </span>
                {incident.offending_sha && (
                  <span className="inline-flex items-center gap-1 rounded bg-slate-900 px-2 py-0.5 font-mono text-xs text-slate-300 ring-1 ring-slate-800">
                    <GitCommitHorizontal className="h-3 w-3 text-slate-400" />
                    {incident.offending_sha.slice(0, 7)}
                  </span>
                )}
                {incident.rollback_executed && (
                  <span className="inline-flex items-center gap-1 rounded border border-amber-500/35 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300">
                    <RotateCcw className="h-3 w-3" />
                    Rollback Executed
                  </span>
                )}
              </div>

              <div className="flex shrink-0 items-center gap-3">
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    incident.resolved_at
                      ? "bg-emerald-500/10 text-emerald-300"
                      : "bg-rose-500/15 text-rose-300"
                  }`}
                >
                  {incident.resolved_at ? "Resolved" : "Open"}
                </span>
                <span className="font-mono text-xs text-slate-500">
                  {new Date(incident.created_at).toLocaleString()}
                </span>
              </div>
            </button>

            {isExpanded && (
              <div className="border-t border-slate-800/80 bg-[#0b0e14] px-5 py-4 space-y-4">
                <div>
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    Metrics Snapshot at Failure
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {snapshotEntries.map(([key, value]) => (
                      <div key={key} className="rounded border border-slate-800/80 bg-[#0f131b] px-2.5 py-2">
                        <div className="truncate text-[10px] uppercase tracking-wider text-slate-500">{key}</div>
                        <div className="mt-0.5 truncate font-mono text-xs text-slate-200">
                          {value === null || value === undefined ? "—" : String(value)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {incident.rollback_output && (
                  <div>
                    <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      <Terminal className="h-3.5 w-3.5 text-amber-400" />
                      Rollback Execution Output
                    </div>
                    <pre className="overflow-x-auto rounded-md border border-slate-800 bg-black/60 p-3 font-mono text-xs leading-relaxed text-slate-300 whitespace-pre-wrap">
                      {incident.rollback_output}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
