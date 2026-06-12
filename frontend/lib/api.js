// API helpers. REST goes through the Next rewrite proxy (/api/*). SSE hits
// the backend origin directly (NEXT_PUBLIC_API_BASE) to avoid proxy buffering.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function jget(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function jsend(path, method, body) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const api = {
  scenarios: () => jget("/api/scenarios"),
  agentStatus: () => jget("/api/agents/status"),
  departments: () => jget("/api/departments"),
  runs: () => jget("/api/runs"),
  startRun: (payload) => jsend("/api/run", "POST", payload),
  costByDepartment: () => jget("/api/analytics/cost-by-department"),
  costPerPassingTask: () => jget("/api/analytics/cost-per-passing-task"),
  spendVsBudget: (period) =>
    jget(`/api/analytics/spend-vs-budget?period=${encodeURIComponent(period)}`),
  tcoProjection: () => jget("/api/analytics/tco-projection"),
  costTimeline: () => jget("/api/analytics/cost-timeline"),
  executive: (period) =>
    jget(`/api/analytics/executive?period=${encodeURIComponent(period)}`),
  efficiency: () => jget("/api/analytics/efficiency"),
  departmentDetail: (id) => jget(`/api/analytics/department/${id}`),
  averages: () => jget("/api/analytics/averages"),
};

// SSE stream URL for one tool of a run (hit backend directly).
export const streamUrl = (runId, tool) =>
  `${API_BASE}/api/stream/${runId}/${tool}`;
