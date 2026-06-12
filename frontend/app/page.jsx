"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { useRun } from "../lib/useRun";
import { project } from "../lib/projection";
import { usd, usd0, pct, int, TOOL_LABEL, TOOL_COLOR } from "../lib/format";
import Leaderboard from "../components/Leaderboard";
import Select from "../components/Select";
import KpiCard from "../components/KpiCard";
import AgentComparison from "../components/AgentComparison";
import MethodologyPanel from "../components/MethodologyPanel";
import EfficiencySection from "../components/EfficiencySection";
import ForecastAlerts from "../components/ForecastAlerts";
import DeptDrilldown from "../components/DeptDrilldown";
import RunsDatabase from "../components/RunsDatabase";
import SpendTrendChart from "../components/charts/SpendTrendChart";
import DeptBudgetChart from "../components/charts/DeptBudgetChart";
import CostShareDonut from "../components/charts/CostShareDonut";

function currentPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wide text-carbon-subtle">{label}</span>
      {children}
    </label>
  );
}

function ChartCard({ title, sub, children }) {
  return (
    <div className="panel p-5">
      <div className="mb-1 font-medium">{title}</div>
      {sub && <div className="text-xs text-carbon-subtle mb-3">{sub}</div>}
      {children}
    </div>
  );
}

// Projection views live here, clearly labeled: this modeling is Planning
// Analytics' job — the web app's deliverable is run → collect → store.
function PaPreviewBand({ children }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="border border-carbon-border rounded-xl overflow-hidden">
      <div className="bg-[#161616] text-white px-5 py-4 flex items-center justify-between gap-4">
        <div>
          <div className="font-semibold">
            Projection Preview{" "}
            <span className="text-white/50 font-normal">— this modeling moves to IBM Planning Analytics</span>
          </div>
          <div className="text-sm text-white/60 mt-0.5">
            The Runs Database above is the dataset PA ingests. These views preview what PA will model:
            cost over time, budget utilization, and scaling by users and months.
          </div>
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          className="shrink-0 border border-white/20 px-3 py-1.5 text-xs rounded-lg hover:bg-white/10 transition-colors"
        >
          {open ? "Collapse" : "Expand"}
        </button>
      </div>
      {open && <div className="p-5 space-y-7 bg-white">{children}</div>}
    </section>
  );
}

export default function UnifiedDashboard() {
  const period = currentPeriod();
  const [exec, setExec] = useState(null);
  const [departmentId, setDepartmentId] = useState("");
  const [runMode, setRunMode] = useState("live");
  const [repeat, setRepeat] = useState(1);
  const [batchInfo, setBatchInfo] = useState(null); // {current, total} during ×N batches
  const [dbRefresh, setDbRefresh] = useState(0); // bump → RunsDatabase refetches
  const [selected, setSelected] = useState(null); // agent to standardize on
  const [overrides, setOverrides] = useState({}); // {deptId: {tool: usd}} from live races
  const [raceDeptId, setRaceDeptId] = useState(null);
  const [agentStatus, setAgentStatus] = useState([]);
  const [autoStarted, setAutoStarted] = useState(false);
  const [err, setErr] = useState(null);

  const { phase, tools, start } = useRun();

  const load = () =>
    Promise.all([api.executive(period), api.agentStatus()])
      .then(([ex, st]) => {
        setExec(ex);
        setAgentStatus(st);
        if (!departmentId && ex.departments[0]) setDepartmentId(String(ex.departments[0].department_id));
        if (!selected) setSelected(ex.recommended_agent);
      })
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  // Capture measured cost/task from a finished race into that department's units.
  useEffect(() => {
    if (raceDeptId == null) return;
    const upd = {};
    for (const [tool, t] of Object.entries(tools)) {
      if (t.status === "done" && t.row?.usd_cost != null) upd[tool] = t.row.usd_cost;
    }
    if (Object.keys(upd).length) {
      setOverrides((prev) => ({ ...prev, [raceDeptId]: { ...prev[raceDeptId], ...upd } }));
    }
  }, [tools, raceDeptId]);

  useEffect(() => {
    if (phase === "complete") {
      const ranked = Object.entries(tools)
        .filter(([, t]) => t.row?.usd_cost != null)
        .sort((a, b) => a[1].row.usd_cost - b[1].row.usd_cost);
      if (ranked[0]) setSelected(ranked[0][0]);
      load();
      setDbRefresh((x) => x + 1);
      // ×N batch: chain the next run after a short beat so the UI can settle.
      setBatchInfo((b) => {
        if (b && b.current < b.total) {
          const next = { current: b.current + 1, total: b.total };
          setTimeout(() => startRunRef.current && startRunRef.current(), 700);
          return next;
        }
        return null;
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Departments with live overrides folded into their per-agent unit costs.
  const departments = useMemo(() => {
    if (!exec) return [];
    return exec.departments.map((d) => ({
      ...d,
      units: { ...d.units, ...(overrides[d.department_id] || {}) },
    }));
  }, [exec, overrides]);

  const proj = useMemo(() => project({ departments, selected }), [departments, selected]);

  const scenarioTitles = useMemo(
    () => Object.fromEntries(departments.map((d) => [d.scenario_id, d.scenario_title])),
    [departments]
  );

  const selectedDept = departments.find((d) => String(d.department_id) === String(departmentId));
  const running = phase === "running";
  // busy spans an entire ×N batch (including the brief idle gap between runs).
  const busy = running || batchInfo !== null;

  const runTotal = useMemo(() => {
    const vals = Object.values(tools).map((t) => t.row?.usd_cost).filter((v) => v != null);
    return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
  }, [tools]);

  // Launch one run with the current selections. Kept in a ref so the batch
  // chain (inside the phase effect) always calls the latest version.
  const startRunRef = useRef(null);
  const startRun = () => {
    if (!selectedDept) return;
    setRaceDeptId(selectedDept.department_id);
    start({
      scenario_id: selectedDept.scenario_id,
      run_mode: runMode,
      department_id: selectedDept.department_id,
      submitter: "demo@ibm.com",
    });
  };
  startRunRef.current = startRun;

  const launch = () => {
    if (!selectedDept) return;
    setBatchInfo(repeat > 1 ? { current: 1, total: repeat } : null);
    startRun();
  };

  // Kiosk/demo auto-launch.
  useEffect(() => {
    if (autoStarted || !selectedDept || phase !== "idle") return;
    if (new URLSearchParams(window.location.search).get("auto") === "1") {
      setAutoStarted(true);
      setRaceDeptId(selectedDept.department_id);
      start({ scenario_id: selectedDept.scenario_id, run_mode: "simulated", department_id: selectedDept.department_id, submitter: "demo@ibm.com" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDept, autoStarted, phase]);

  if (err) return <div className="panel p-4 text-carbon-red text-sm">Backend error: {err}. Is the API on :8000?</div>;
  if (!proj || !selectedDept) return <div className="text-sm text-carbon-subtle">Loading…</div>;

  const k = proj.kpis;
  const selLabel = TOOL_LABEL[proj.selected] || proj.selected;
  const baseLabel = TOOL_LABEL[proj.baseline_agent] || proj.baseline_agent;

  return (
    <div className="space-y-7">
      {/* Title + standardize-on context */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Executive Overview</h1>
          <p className="text-carbon-subtle text-sm mt-0.5">
            Pick a department, run its real task across IBM BOB, Claude, and Copilot, and see the
            org-wide budget impact of standardizing on each.
          </p>
        </div>
        <div className="flex items-center gap-2.5 text-sm">
          <span className="text-carbon-subtle">Standardizing on</span>
          <span className="inline-flex items-center gap-2 pl-2.5 pr-3 py-1.5 bg-white border border-carbon-border rounded-full font-medium shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: TOOL_COLOR[proj.selected] }} />
            {selLabel}
          </span>
        </div>
      </div>

      {/* ---- DEPARTMENT + TASK ---- */}
      <section className="space-y-3">
        <div className="panel p-5">
          <div className="flex flex-wrap items-end gap-5">
            <Field label="Department">
              <Select className="min-w-[170px]" value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} disabled={busy}>
                {departments.map((d) => (
                  <option key={d.department_id} value={d.department_id}>{d.department}</option>
                ))}
              </Select>
            </Field>
            <Field label="Mode">
              <Select className="min-w-[140px]" value={runMode} onChange={(e) => setRunMode(e.target.value)} disabled={busy}>
                <option value="live">Live</option>
                <option value="simulated">Simulated</option>
                <option value="replay">Replay</option>
              </Select>
            </Field>
            <Field label="Runs">
              <Select className="min-w-[90px]" value={repeat} onChange={(e) => setRepeat(Number(e.target.value))} disabled={busy}>
                {[1, 3, 5, 10, 20].map((n) => <option key={n} value={n}>×{n}</option>)}
              </Select>
            </Field>
            <div className="ml-auto flex items-center gap-5">
              {runTotal != null && (
                <div className="text-right">
                  <div className="text-xs uppercase tracking-wide text-carbon-subtle">Task total</div>
                  <div className="metric-num text-xl font-semibold">{usd(runTotal)}</div>
                </div>
              )}
              <button className="btn-primary" onClick={launch} disabled={busy}>
                {busy
                  ? batchInfo ? `Running ${batchInfo.current} of ${batchInfo.total}…` : "Running…"
                  : repeat > 1 ? `▶  Run ×${repeat}` : "▶  Run this task"}
              </button>
            </div>
          </div>
          {runMode === "live" && (
            <p className="text-xs text-carbon-subtle mt-2">
              Live runs call the real agent APIs and spend real credits (typically $0.50–$3 per agent per run).
            </p>
          )}

          {/* The department's representative task */}
          <div className="mt-4 pt-4 border-t border-carbon-border">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs uppercase tracking-wide text-carbon-subtle">{selectedDept.department}&apos;s task</span>
              {selectedDept.scenario_type && (
                <span className="tag bg-carbon-bg text-carbon-subtle capitalize">{selectedDept.scenario_type}</span>
              )}
            </div>
            <div className="font-medium">{selectedDept.scenario_title}</div>
            <p className="text-sm text-carbon-subtle mt-0.5 max-w-4xl">{selectedDept.scenario_description}</p>
          </div>
        </div>

        {runMode === "live" && agentStatus.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs px-1">
            {agentStatus.map((a) => (
              <span key={a.tool} className="inline-flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${a.live_ready ? "bg-carbon-green" : "bg-carbon-subtle/40"}`} />
                <span className="font-medium">{TOOL_LABEL[a.tool] || a.tool}</span>
                <span className="text-carbon-subtle">{a.live_ready ? "live (real API)" : "recorded (CLI not installed)"}</span>
              </span>
            ))}
          </div>
        )}

        <Leaderboard tools={tools} selected={selected} onSelect={setSelected} />
        <p className="text-xs text-carbon-subtle">
          {running
            ? `All three agents are running ${selectedDept.department}'s task simultaneously…`
            : "Click any agent to project the org-wide budget as if every department standardized on it."}
        </p>
      </section>

      {/* ---- THE DELIVERABLE: every run captured + stored ---- */}
      <RunsDatabase refreshKey={dbRefresh} scenarioTitles={scenarioTitles} />

      <EfficiencySection refreshKey={dbRefresh} />

      {/* ---- PROJECTIONS: Planning Analytics' job; shown here as a preview ---- */}
      <PaPreviewBand>
        <div className={`rounded-xl border-l-4 px-5 py-4 ${k.on_track ? "bg-carbon-green/[0.08] border-carbon-green" : "bg-carbon-red/[0.08] border-carbon-red"}`}>
          <div className="flex items-center gap-3">
            <span className={`text-xl ${k.on_track ? "text-carbon-green" : "text-carbon-red"}`}>{k.on_track ? "✓" : "!"}</span>
            <div>
              <div className="font-semibold">{k.on_track ? "Budget On Track" : "Over Budget"}</div>
              <div className="text-sm text-carbon-subtle">
                Standardizing on <span className="font-medium text-carbon-text">{selLabel}</span> projects{" "}
                {usd0(k.projected_monthly_usd)}/mo across all departments against a {usd0(k.total_budget_usd)} budget — {pct(k.budget_utilization)} utilized.
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Projected Annual Spend" value={k.projected_annual_usd} format={usd0}
            delta={`${pct(k.savings_pct)} vs ${baseLabel}`} deltaPositive sub={`On ${selLabel} · ${int(k.monthly_task_volume)} tasks/mo`} />
          <KpiCard label="Annual Savings" value={k.savings_annual_usd} format={usd0}
            delta={`${usd0(k.savings_monthly_usd)}/mo`} deltaPositive sub={`vs most expensive agent (${baseLabel})`} />
          <KpiCard label="Monthly Burn Rate" value={k.projected_monthly_usd} format={usd0}
            sub={`of ${usd0(k.total_budget_usd)} monthly budget`} />
          <KpiCard label="Budget Remaining" value={k.budget_remaining_usd} format={usd0}
            sub={`${pct(1 - (k.budget_utilization || 0))} available this period`} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ChartCard title="Monthly Spend Trend" sub={`${baseLabel} baseline vs. ${selLabel} (selected)`}>
            <SpendTrendChart trend={proj.trend} baselineLabel={baseLabel} recLabel={selLabel} />
          </ChartCard>
          <ChartCard title="Department Budget vs. Projected" sub="Planning Analytics budget vs. projected agent spend">
            <DeptBudgetChart departments={proj.departments} />
          </ChartCard>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ChartCard title="Projected Spend by Department" sub="Share of monthly AI-agent spend">
            <CostShareDonut data={proj.cost_share} />
          </ChartCard>
          <div className="space-y-3">
            <div className="font-medium">Agent Comparison <span className="text-carbon-subtle text-sm font-normal">— click to standardize</span></div>
            <AgentComparison agents={proj.agents} selected={proj.selected} onSelect={setSelected} />
          </div>
        </div>

        <ForecastAlerts proj={proj} selectedLabel={selLabel} />

        <DeptDrilldown proj={proj} selectedLabel={selLabel} />
      </PaPreviewBand>

      <MethodologyPanel />
    </div>
  );
}
