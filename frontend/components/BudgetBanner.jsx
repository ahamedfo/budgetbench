"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { usd, pct } from "../lib/format";

// Period of the current month, "YYYY-MM" — matches the backend's period key.
function currentPeriod() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function BudgetBanner({ departmentId, period, runTotalUsd, refreshKey }) {
  const [row, setRow] = useState(null);
  const p = period || currentPeriod();

  useEffect(() => {
    if (!departmentId) return;
    let alive = true;
    api
      .spendVsBudget(p)
      .then((rows) => {
        if (!alive) return;
        setRow(rows.find((r) => r.department_id === Number(departmentId)) || null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [departmentId, p, refreshKey]);

  if (!departmentId || !row) return null;

  const util = row.utilization || 0;
  const over = row.over_budget;
  const barColor = over ? "bg-carbon-red" : util > 0.85 ? "bg-carbon-yellow" : "bg-carbon-green";

  return (
    <div className="panel p-5">
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="font-semibold">
          {row.department} · budget vs. spend{" "}
          <span className="text-carbon-subtle font-normal text-sm">({p})</span>
        </h3>
        {runTotalUsd != null && (
          <span className="text-sm text-carbon-subtle">
            This task added{" "}
            <span className="metric-num font-semibold text-carbon-text">{usd(runTotalUsd)}</span>
          </span>
        )}
      </div>

      <div className="flex items-end justify-between mb-2">
        <div className="metric-num text-2xl font-semibold">{usd(row.spend_usd)}</div>
        <div className="metric-num text-sm text-carbon-subtle">
          of {usd(row.budget_usd)} · {pct(util)} used
        </div>
      </div>

      <div className="h-2.5 w-full bg-carbon-bg overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all duration-700`}
          style={{ width: `${Math.min(util * 100, 100)}%` }}
        />
      </div>

      <div className="mt-2 text-sm text-carbon-subtle">
        {over ? (
          <span className="text-carbon-red font-medium">Over budget by {usd(-row.remaining_usd)}</span>
        ) : (
          <>
            <span className="metric-num text-carbon-text font-medium">{usd(row.remaining_usd)}</span>{" "}
            remaining · {row.tasks} task{row.tasks === 1 ? "" : "s"} this period · written back to Planning Analytics
          </>
        )}
      </div>
    </div>
  );
}
