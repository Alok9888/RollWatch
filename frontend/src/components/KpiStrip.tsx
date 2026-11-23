"use client";

import { Activity, AlertTriangle, CheckCircle2, RotateCcw } from "lucide-react";
import type { Incident, Target } from "@/types/rollwatch";

interface KpiStripProps {
  targets: Target[];
  incidents: Incident[];
}

export function KpiStrip({ targets, incidents }: KpiStripProps) {
  const totalTargets = targets.length;
  const healthyCount = targets.filter((t) => t.status === "healthy").length;
  const activeDriftCount = targets.filter((t) => t.version_drift || t.header_drift || t.status === "drifted").length;
  const totalRollbacks = incidents.filter((i) => i.rollback_executed).length;
  const healthyRatio = totalTargets > 0 ? Math.round((healthyCount / totalTargets) * 100) : 100;

  const cards = [
    {
      label: "Monitored Targets",
      value: String(totalTargets),
      sub: `${targets.filter((t) => t.mode === "managed").length} managed · ${targets.filter((t) => t.mode === "external").length} external`,
      icon: Activity,
      accent: "text-sky-400",
      border: "border-slate-800/80",
    },
    {
      label: "Healthy Count",
      value: `${healthyCount}/${totalTargets}`,
      sub: totalTargets > 0 ? `${healthyRatio}% fleet healthy` : "No targets registered",
      icon: CheckCircle2,
      accent: healthyCount === totalTargets ? "text-emerald-400" : "text-amber-400",
      border: "border-slate-800/80",
    },
    {
      label: "Active Drift Alerts",
      value: String(activeDriftCount),
      sub: activeDriftCount > 0 ? "SHA or response header mismatch" : "All live versions aligned",
      icon: AlertTriangle,
      accent: activeDriftCount > 0 ? "text-rose-400" : "text-slate-400",
      border: activeDriftCount > 0 ? "border-rose-500/35" : "border-slate-800/80",
    },
    {
      label: "Total Auto-Rollbacks",
      value: String(totalRollbacks),
      sub: `${incidents.length} total recorded incidents`,
      icon: RotateCcw,
      accent: totalRollbacks > 0 ? "text-amber-400" : "text-slate-400",
      border: "border-slate-800/80",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.label}
            className={`rounded-lg border ${card.border} bg-[#0f131b] px-4 py-3.5 transition-colors hover:bg-[#131823]`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-slate-400">{card.label}</span>
              <Icon className={`h-4 w-4 ${card.accent}`} />
            </div>
            <div className="mt-2 font-mono text-2xl font-semibold tracking-tight text-slate-100">{card.value}</div>
            <div className="mt-1 text-xs text-slate-500">{card.sub}</div>
          </div>
        );
      })}
    </div>
  );
}
