"use client";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TOOL_LABEL, TOOL_COLOR, usd } from "../lib/format";

export default function TcoChart({ tco }) {
  if (!tco || !tco.by_tool || tco.by_tool.length === 0) {
    return <div className="text-sm text-carbon-subtle py-8 text-center">No data yet.</div>;
  }
  const data = tco.by_tool.map((t) => ({
    name: TOOL_LABEL[t.tool] || t.tool,
    tool: t.tool,
    annual: t.projected_annual_usd,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid stroke="#e0e0e0" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#525252" }} axisLine={{ stroke: "#e0e0e0" }} tickLine={false} />
        <YAxis
          tick={{ fontSize: 12, fill: "#525252" }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => usd(v)}
          width={70}
        />
        <Tooltip
          formatter={(v) => [usd(v), "Projected annual"]}
          contentStyle={{ border: "1px solid #e0e0e0", borderRadius: 0, fontSize: 12 }}
        />
        <Bar dataKey="annual" radius={[0, 0, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.tool} fill={TOOL_COLOR[d.tool] || "#0f62fe"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
