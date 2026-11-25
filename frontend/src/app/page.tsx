"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertOctagon, Plus, Radio, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { BackendHealth, Incident, Target, TargetCreatePayload } from "@/types/rollwatch";
import { AddTargetModal } from "@/components/AddTargetModal";
import { IncidentsView } from "@/components/IncidentsView";
import { KpiStrip } from "@/components/KpiStrip";
import { TargetDetailDrawer } from "@/components/TargetDetailDrawer";
import { TargetsTable } from "@/components/TargetsTable";

export default function DashboardPage() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [activeTab, setActiveTab] = useState<"targets" | "incidents">("targets");
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [checkingIds, setCheckingIds] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [targetsData, incidentsData, healthData] = await Promise.all([
        api.listTargets(),
        api.listIncidents(),
        api.getHealth(),
      ]);
      setTargets(targetsData);
      setIncidents(incidentsData);
      setHealth(healthData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reach RollWatch API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData]);

  const selectedTarget = targets.find((t) => t.id === selectedTargetId) ?? null;

  const handleCreateTarget = async (payload: TargetCreatePayload) => {
    const created = await api.createTarget(payload);
    await loadData();
    // Run an immediate probe so metrics appear right away in the table
    setCheckingIds((prev) => ({ ...prev, [created.id]: true }));
    try {
      await api.checkNow(created.id);
    } finally {
      setCheckingIds((prev) => ({ ...prev, [created.id]: false }));
      await loadData();
    }
  };

  const handleCheckNow = async (targetId: string) => {
    setCheckingIds((prev) => ({ ...prev, [targetId]: true }));
    try {
      await api.checkNow(targetId);
      await loadData();
    } finally {
      setCheckingIds((prev) => ({ ...prev, [targetId]: false }));
    }
  };

  const handleDeleteTarget = async (targetId: string) => {
    await api.deleteTarget(targetId);
    if (selectedTargetId === targetId) {
      setSelectedTargetId(null);
    }
    await loadData();
  };

  const openIncidentsCount = incidents.filter((i) => !i.resolved_at).length;

  return (
    <div className="min-h-screen bg-[#090b10] text-slate-100">
      {/* Top Navbar */}
      <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-[#090b10]/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-sky-500/40 bg-sky-500/15 text-sky-400">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-sm font-semibold tracking-tight text-slate-100">RollWatch</h1>
                <span className="rounded border border-slate-800 bg-[#0f131b] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {health ? health.git_sha.slice(0, 7) : "offline"}
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                Deployment-Aware Health, Drift &amp; Auto-Rollback Monitor
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="hidden items-center gap-1.5 rounded-full border border-slate-800 bg-[#0f131b] px-2.5 py-1 text-[11px] text-slate-400 sm:flex">
              <Radio
                className={`h-3 w-3 ${health?.status === "ok" ? "text-emerald-400" : "text-rose-400"}`}
              />
              {health?.status === "ok" ? "Live · 5s poll" : "API disconnected"}
            </div>
            <button
              type="button"
              onClick={loadData}
              title="Refresh now"
              className="rounded-md border border-slate-800 bg-[#0f131b] p-2 text-slate-400 transition-colors hover:border-slate-700 hover:text-slate-100"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setModalOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-sky-500 px-3.5 py-2 text-xs font-semibold text-slate-950 transition-colors hover:bg-sky-400"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Target
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
        {error && (
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
            API connection error ({api.baseUrl}): {error}
          </div>
        )}

        <KpiStrip targets={targets} incidents={incidents} />

        {/* View Tabs */}
        <div className="flex items-center justify-between border-b border-slate-800/80">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setActiveTab("targets")}
              className={`inline-flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-semibold transition-colors ${
                activeTab === "targets"
                  ? "border-sky-400 text-sky-300"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <Activity className="h-3.5 w-3.5" />
              Targets
              <span className="rounded bg-slate-800/90 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
                {targets.length}
              </span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("incidents")}
              className={`inline-flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-semibold transition-colors ${
                activeTab === "incidents"
                  ? "border-sky-400 text-sky-300"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              <AlertOctagon className="h-3.5 w-3.5" />
              Incidents
              <span
                className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                  openIncidentsCount > 0
                    ? "bg-rose-500/20 text-rose-300"
                    : "bg-slate-800/90 text-slate-300"
                }`}
              >
                {incidents.length}
              </span>
            </button>
          </div>
          <div className="hidden pb-2 text-[11px] text-slate-500 sm:block">
            Prometheus metrics: <code className="font-mono text-slate-400">{api.baseUrl}/metrics</code>
          </div>
        </div>

        {loading ? (
          <div className="rounded-lg border border-slate-800 bg-[#0f131b] p-10 text-center text-xs text-slate-400">
            Connecting to RollWatch telemetry engine...
          </div>
        ) : activeTab === "targets" ? (
          <TargetsTable
            targets={targets}
            checkingIds={checkingIds}
            onSelect={(t) => setSelectedTargetId(t.id)}
            onCheckNow={handleCheckNow}
            onDelete={handleDeleteTarget}
          />
        ) : (
          <IncidentsView incidents={incidents} />
        )}
      </main>

      <AddTargetModal open={modalOpen} onClose={() => setModalOpen(false)} onSubmit={handleCreateTarget} />

      <TargetDetailDrawer
        target={selectedTarget}
        onClose={() => setSelectedTargetId(null)}
        onDataChanged={loadData}
      />
    </div>
  );
}
