"use client";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";
import { usd0 } from "../../lib/format";

const PALETTE = ["#0f62fe", "#8a3ffc", "#33b1ff", "#007d79", "#ff7eb6", "#fa4d56"];

// Donut of projected spend share by department.
export default function CostShareDonut({ data }) {
  if (!data || data.length === 0)
    return <div className="h-[260px] grid place-items-center text-sm text-carbon-subtle">No data yet.</div>;

  const rows = data.map((d) => ({ name: d.department, value: d.value }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie
          data={rows}
          dataKey="value"
          nameKey="name"
          innerRadius={62}
          outerRadius={96}
          paddingAngle={1}
          stroke="none"
          isAnimationActive={false}
        >
          {rows.map((r, i) => (
            <Cell key={r.name} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip formatter={(v) => usd0(v)} contentStyle={{ border: "1px solid #e0e0e0", borderRadius: 0, fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} verticalAlign="middle" align="right" layout="vertical" />
      </PieChart>
    </ResponsiveContainer>
  );
}
