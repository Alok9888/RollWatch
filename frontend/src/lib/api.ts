import type {
  BackendHealth,
  Deployment,
  Incident,
  ProbeResult,
  RollbackExecutionResult,
  Target,
  TargetCreatePayload,
} from "@/types/rollwatch";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
        detail = body.detail[0].msg;
      }
    } catch {
      // Ignore JSON parse failures on non-JSON error responses
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  baseUrl: API_BASE,
  getHealth: () => request<BackendHealth>("/health"),
  listTargets: () => request<Target[]>("/api/targets"),
  getTarget: (id: string) => request<Target>(`/api/targets/${id}`),
  createTarget: (payload: TargetCreatePayload) =>
    request<Target>("/api/targets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteTarget: (id: string) =>
    request<void>(`/api/targets/${id}`, {
      method: "DELETE",
    }),
  getProbes: (targetId: string, limit = 60) =>
    request<ProbeResult[]>(`/api/targets/${targetId}/probes?limit=${limit}`),
  checkNow: (targetId: string) =>
    request<ProbeResult>(`/api/targets/${targetId}/check-now`, {
      method: "POST",
    }),
  getDeployments: (targetId: string) =>
    request<Deployment[]>(`/api/targets/${targetId}/deployments`),
  triggerRollback: (targetId: string, rollbackToTag?: string, reason?: string) =>
    request<RollbackExecutionResult>(`/api/targets/${targetId}/rollback`, {
      method: "POST",
      body: JSON.stringify({
        rollback_to_tag: rollbackToTag || null,
        reason: reason || "Manual rollback from RollWatch dashboard",
      }),
    }),
  listIncidents: (targetId?: string) =>
    request<Incident[]>(targetId ? `/api/incidents?target_id=${targetId}` : "/api/incidents"),
};
