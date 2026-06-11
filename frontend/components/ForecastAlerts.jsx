"use client";
import { usd0, pct } from "../lib/format";

// Per-department forecast + alerts, computed from the live projection so it
// reacts instantly when you switch the selected agent.
export default function ForecastAlerts({ proj, selectedLabel }) {
  if (!proj) return null;
  const depts = proj.departments.map((d) => {
    const util = d.utilization || 0;
    const daysToBudget = d.projected_usd > 0 ? (d.budget_usd * 30) / d.projected_usd : Infinity;
    const status = d.over_budget ? "over" : util > 0.85 ? "warning" : "ok";
    return { ...d, util, daysToBudget, status };
  });
  const over = depts.filter((d) => d.status === "over");
  const warn = depts.filter((d) => d.status === "warning");

  const alertTone =
    over.length > 0 ? "red" : warn.length > 0 ? "yellow" : "green";
  const toneCls = {
    red: "bg-carbon-red/[0.08] border-carbon-red",
    yellow: "bg-carbon-yellow/[0.12] border-carbon-yellow",
    green: "bg-carbon-green/[0.08] border-carbon-green",
  }[alertTone];

  return (
    <section>
      <h2 className="text-base font-semibold mb-1">Budget Forecast &amp; Alerts</h2>
      <p className="text-sm text-carbon-subtle mb-3">
        Month-end forecast on <span className="font-medium text-carbon-text">{selectedLabel}</span> vs. each
        department&apos;s Planning Analytics budget.
      </p>

      <div className={`rounded-xl border-l-4 px-4 py-3 mb-4 text-sm ${toneCls}`}>
        {over.length > 0 ? (
          <span><span className="font-semibold text-carbon-red">{over.length} department{over.length > 1 ? "s" : ""} over budget</span> on {selectedLabel}: {over.map((d) => d.department).join(", ")}.</span>
        ) : warn.length > 0 ? (
          <span><span className="font-semibold text-[#8a6d00]">{warn.length} department{warn.length > 1 ? "s" : ""} near budget</span> (&gt;85%): {warn.map((d) => d.department).join(", ")}.</span>
        ) : (
          <span><span className="font-semibold text-carbon-green">All departments within budget</span> on {selectedLabel}.</span>
        )}
      </div>

      <div className="panel overflow-hidden">
        <div className="grid grid-cols-[1.2fr_1fr_1fr_1.4fr_0.9fr] px-5 py-3 text-[11px] uppercase tracking-wider text-carbon-subtle border-b border-carbon-border bg-carbon-bg/40">
          <div>Department</div>
          <div className="text-right">Budget</div>
          <div className="text-right">Forecast</div>
          <div className="px-3">Utilization</div>
          <div className="text-right">Runway</div>
        </div>
        {depts.map((d) => {
          const barColor = d.status === "over" ? "bg-carbon-red" : d.status === "warning" ? "bg-carbon-yellow" : "bg-carbon-green";
          return (
            <div key={d.department_id} className="grid grid-cols-[1.2fr_1fr_1fr_1.4fr_0.9fr] items-center px-5 py-3.5 border-b border-carbon-border last:border-b-0">
              <div className="font-medium">{d.department}</div>
              <div className="metric-num text-right text-sm">{usd0(d.budget_usd)}</div>
              <div className="metric-num text-right text-sm font-semibold">{usd0(d.projected_usd)}</div>
              <div className="px-3">
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 bg-carbon-bg rounded-full overflow-hidden">
                    <div className={`h-full ${barColor}`} style={{ width: `${Math.min(d.util * 100, 100)}%` }} />
                  </div>
                  <span className="metric-num text-xs text-carbon-subtle w-9 text-right">{pct(d.util)}</span>
                </div>
              </div>
              <div className="text-right text-sm">
                {d.daysToBudget >= 30 ? (
                  <span className="text-carbon-green">covers month</span>
                ) : (
                  <span className="text-carbon-red font-medium">day {Math.max(1, Math.floor(d.daysToBudget))}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
