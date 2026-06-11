"use client";
import { TOOL_LABEL, TOOL_COLOR, usd, usd0 } from "../lib/format";

// Clickable agent cards. Selecting one re-projects the whole dashboard as if
// the org standardized on that agent.
export default function AgentComparison({ agents, selected, onSelect }) {
  if (!agents || agents.length === 0)
    return <div className="panel p-4 text-sm text-carbon-subtle">No agent runs yet.</div>;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {agents.map((a) => {
        const isSel = a.tool === selected;
        return (
          <button
            key={a.tool}
            onClick={() => onSelect && onSelect(a.tool)}
            className={`panel p-4 border-l-4 text-left transition-all ${
              isSel ? "ring-2 ring-carbon-blue shadow-sm" : "hover:bg-carbon-bg/60"
            }`}
            style={{ borderLeftColor: TOOL_COLOR[a.tool] || "#0f62fe" }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold">{TOOL_LABEL[a.tool] || a.tool}</span>
              {a.recommended ? (
                <span className="tag bg-carbon-green/10 text-carbon-green">✓ Recommended</span>
              ) : isSel ? (
                <span className="tag bg-carbon-blue/10 text-carbon-blue">selected</span>
              ) : (
                <span className="tag bg-carbon-bg text-carbon-subtle">evaluate</span>
              )}
            </div>
            <div className="text-xs uppercase tracking-wide text-carbon-subtle">Cost / task</div>
            <div className="metric-num text-2xl font-semibold">{usd(a.unit_usd)}</div>
            <div className="mt-3 flex justify-between text-sm">
              <span className="text-carbon-subtle">Projected / yr</span>
              <span className="metric-num font-medium">{usd0(a.projected_annual_usd)}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
