"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { TOOL_LABEL, TOOL_COLOR, usd, int, secs } from "../lib/format";

function TokenMix({ input, output, cached }) {
  const total = (input || 0) + (output || 0) + (cached || 0) || 1;
  const seg = (v, color) => (
    <div style={{ width: `${((v || 0) / total) * 100}%`, background: color }} className="h-full" />
  );
  return (
    <div>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-carbon-bg">
        {seg(input, "#0f62fe")}
        {seg(cached, "#a6c8ff")}
        {seg(output, "#24a148")}
      </div>
      <div className="flex gap-3 mt-1.5 text-[11px] text-carbon-subtle">
        <span><span className="inline-block w-2 h-2 rounded-full align-middle mr-1" style={{ background: "#0f62fe" }} />in {int(input)}</span>
        <span><span className="inline-block w-2 h-2 rounded-full align-middle mr-1" style={{ background: "#a6c8ff" }} />cache {int(cached)}</span>
        <span><span className="inline-block w-2 h-2 rounded-full align-middle mr-1" style={{ background: "#24a148" }} />out {int(output)}</span>
      </div>
    </div>
  );
}

export default function EfficiencySection({ refreshKey }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    api.efficiency().then(setRows).catch(() => {});
  }, [refreshKey]);
  if (rows.length === 0) return null;

  // Best (highest) tokens-per-dollar gets a subtle highlight.
  const bestTPD = Math.max(...rows.map((r) => r.tokens_per_dollar || 0));

  return (
    <section>
      <h2 className="text-base font-semibold mb-1">Operations · Speed &amp; Efficiency</h2>
      <p className="text-sm text-carbon-subtle mb-3">Time per task, token mix, and how many tokens each agent delivers per dollar.</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {rows.map((r) => {
          const best = r.tokens_per_dollar === bestTPD && bestTPD > 0;
          return (
            <div key={r.tool} className="panel p-4 border-l-4" style={{ borderLeftColor: TOOL_COLOR[r.tool] }}>
              <div className="flex items-center justify-between mb-3">
                <span className="font-semibold">{TOOL_LABEL[r.tool] || r.tool}</span>
                {best && <span className="tag bg-carbon-green/10 text-carbon-green">most efficient</span>}
              </div>
              <div className="grid grid-cols-3 gap-2 mb-3">
                <Metric label="Time/task" value={secs(r.avg_duration_ms)} />
                <Metric label="Tokens/task" value={int(r.avg_tokens_per_task)} />
                <Metric label="Tokens / $" value={r.tokens_per_dollar ? int(r.tokens_per_dollar) : "—"} />
              </div>
              <TokenMix input={r.avg_input_tokens} output={r.avg_output_tokens} cached={r.avg_cached_tokens} />
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Metric({ label, value }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-carbon-subtle">{label}</div>
      <div className="metric-num text-lg font-semibold leading-tight">{value}</div>
    </div>
  );
}
