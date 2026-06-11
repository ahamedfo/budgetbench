"use client";
import { useCountUp } from "../lib/useCountUp";

// Executive KPI tile with an animated value, so the number visibly shifts
// when the selected agent changes or a live result lands.
export default function KpiCard({ label, value, format, delta, deltaPositive = true, sub }) {
  const animated = useCountUp(typeof value === "number" ? value : null);
  const display = typeof value === "number" ? format(animated) : value;
  return (
    <div className="panel p-5">
      <div className="text-xs uppercase tracking-wide text-carbon-subtle mb-2">{label}</div>
      <div className="text-3xl font-semibold leading-none tracking-tight" style={{ fontVariantNumeric: "tabular-nums" }}>
        {display}
      </div>
      {delta && (
        <div className={`text-sm mt-2 ${deltaPositive ? "text-carbon-green" : "text-carbon-red"}`}>
          {deltaPositive ? "↓" : "↑"} {delta}
        </div>
      )}
      {sub && <div className="text-xs text-carbon-subtle mt-1">{sub}</div>}
    </div>
  );
}
