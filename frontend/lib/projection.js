// Client-side projection so executive metrics recompute instantly when you
// pick a different agent or a live race lands new costs. Works off
// per-department, per-agent unit costs (each department runs its own task).

function trailingMonths(n) {
  const out = [];
  const d = new Date();
  for (let i = 0; i < n; i++) {
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
    d.setMonth(d.getMonth() - 1);
  }
  return out.reverse();
}

const RAMP = [0.82, 0.86, 0.9, 0.94, 0.97, 1.0];

// departments: [{department, department_id, budget_usd, volume, units:{tool:usd}, scenario_*}]
// selected: tool to standardize on.
export function project({ departments, selected }) {
  if (!departments || departments.length === 0) return null;
  const tools = Array.from(new Set(departments.flatMap((d) => Object.keys(d.units || {}))));
  if (tools.length === 0) return null;

  const orgMonthly = {};
  for (const t of tools) {
    orgMonthly[t] = departments.reduce((s, d) => s + (d.units?.[t] || 0) * (d.volume || 0), 0);
  }
  const recommended = tools.reduce((a, b) => (orgMonthly[b] < orgMonthly[a] ? b : a), tools[0]);
  const baseline = tools.reduce((a, b) => (orgMonthly[b] > orgMonthly[a] ? b : a), tools[0]);
  const sel = selected && tools.includes(selected) ? selected : recommended;

  const totalVolume = departments.reduce((s, d) => s + (d.volume || 0), 0);
  const totalBudget = departments.reduce((s, d) => s + (d.budget_usd || 0), 0);

  const deptRows = departments.map((d) => {
    const projected = (d.units?.[sel] || 0) * (d.volume || 0);
    return {
      department: d.department,
      department_id: d.department_id,
      budget_usd: d.budget_usd || 0,
      projected_usd: projected,
      volume: d.volume || 0,
      scenario_title: d.scenario_title,
      scenario_description: d.scenario_description,
      scenario_type: d.scenario_type,
      units: d.units,
      utilization: d.budget_usd ? projected / d.budget_usd : null,
      over_budget: !!(d.budget_usd && projected > d.budget_usd),
    };
  });

  const projectedMonthly = orgMonthly[sel];
  const baselineMonthly = orgMonthly[baseline];
  const savingsMonthly = baselineMonthly - projectedMonthly;

  const months = trailingMonths(6);
  const trend = months.map((mo, i) => ({
    period: mo,
    baseline_usd: baselineMonthly * RAMP[i],
    recommended_usd: projectedMonthly * RAMP[i],
  }));

  const agents = tools
    .map((t) => ({
      tool: t,
      unit_usd: totalVolume ? orgMonthly[t] / totalVolume : 0,
      projected_monthly_usd: orgMonthly[t],
      projected_annual_usd: orgMonthly[t] * 12,
      recommended: t === recommended,
      selected: t === sel,
    }))
    .sort((a, b) => a.projected_monthly_usd - b.projected_monthly_usd);

  return {
    selected: sel,
    recommended_agent: recommended,
    baseline_agent: baseline,
    kpis: {
      projected_monthly_usd: projectedMonthly,
      projected_annual_usd: projectedMonthly * 12,
      total_budget_usd: totalBudget,
      budget_remaining_usd: totalBudget - projectedMonthly,
      budget_utilization: totalBudget ? projectedMonthly / totalBudget : null,
      savings_monthly_usd: savingsMonthly,
      savings_annual_usd: savingsMonthly * 12,
      savings_pct: baselineMonthly ? savingsMonthly / baselineMonthly : null,
      monthly_task_volume: totalVolume,
      on_track: projectedMonthly <= totalBudget,
    },
    departments: deptRows,
    trend,
    cost_share: deptRows.filter((r) => r.projected_usd > 0).map((r) => ({ department: r.department, value: r.projected_usd })),
    agents,
  };
}
