"use client";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usdCompact, usd0 } from "../../lib/format";

// Grouped bars: each department's PA budget vs. projected agent spend.
export default function DeptBudgetChart({ departments }) {
  if (!departments || departments.length === 0)
    return <div className="h-[260px] grid place-items-center text-sm text-carbon-subtle">No data yet.</div>;

  const data = departments.map((d) => ({
    name: d.department,
    Budget: d.budget_usd,
    Projected: d.projected_usd,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 8 }} barGap={4}>
        <CartesianGrid stroke="#e0e0e0" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#525252" }} tickLine={false} axisLine={{ stroke: "#e0e0e0" }} />
        <YAxis tick={{ fontSize: 12, fill: "#525252" }} tickLine={false} axisLine={false} tickFormatter={usdCompact} width={56} />
        <Tooltip formatter={(v) => usd0(v)} contentStyle={{ border: "1px solid #e0e0e0", borderRadius: 0, fontSize: 12 }} cursor={{ fill: "#f4f4f4" }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Budget" fill="#c6c6c6" isAnimationActive={false} />
        <Bar dataKey="Projected" fill="#0f62fe" isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}
