"use client";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usdCompact, usd0 } from "../../lib/format";

// "Before vs After Control Stack": baseline (most expensive agent) vs the
// recommended agent, over the trailing months.
export default function SpendTrendChart({ trend, baselineLabel = "Baseline", recLabel = "Recommended" }) {
  if (!trend || trend.length === 0)
    return <div className="h-[260px] grid place-items-center text-sm text-carbon-subtle">No data yet.</div>;

  const data = trend.map((t) => ({
    period: t.period.slice(2), // "26-01"
    [baselineLabel]: t.baseline_usd,
    [recLabel]: t.recommended_usd,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="gBase" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#da1e28" stopOpacity={0.18} />
            <stop offset="100%" stopColor="#da1e28" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="gRec" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#24a148" stopOpacity={0.22} />
            <stop offset="100%" stopColor="#24a148" stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#e0e0e0" vertical={false} />
        <XAxis dataKey="period" tick={{ fontSize: 12, fill: "#525252" }} tickLine={false} axisLine={{ stroke: "#e0e0e0" }} />
        <YAxis tick={{ fontSize: 12, fill: "#525252" }} tickLine={false} axisLine={false} tickFormatter={usdCompact} width={56} />
        <Tooltip formatter={(v) => usd0(v)} contentStyle={{ border: "1px solid #e0e0e0", borderRadius: 0, fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Area type="monotone" dataKey={baselineLabel} stroke="#da1e28" strokeWidth={2} fill="url(#gBase)" dot={{ r: 3 }} isAnimationActive={false} />
        <Area type="monotone" dataKey={recLabel} stroke="#24a148" strokeWidth={2} fill="url(#gRec)" dot={{ r: 3 }} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
