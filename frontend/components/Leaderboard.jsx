"use client";
import { TOOL_LABEL, TOOL_COLOR, usd, tokens, secs } from "../lib/format";

// Lower sort key = higher on the board. Finished+passing agents sort by
// cost ascending (cheapest passing wins — the hero metric). Running agents
// sit below finished ones; failed/errored sink to the bottom.
function sortKey(t) {
  const cost = t.row ? t.row.usd_cost : t.liveUsd;
  const passed = verifyPassed(t);
  if (t.status === "done" && passed) return [0, cost ?? 9e9];
  if (t.status === "done" && !passed) return [2, cost ?? 9e9];
  if (t.status === "error") return [3, 9e9];
  return [1, t.elapsedMs / 1000]; // running
}

function verifyPassed(t) {
  const v = t.row && t.row.verification;
  if (!v) return false;
  return !!v.verify_sh_passed || ((v.tests_total || 0) > 0 && (v.tests_failed || 0) === 0);
}

function StatusPill({ t }) {
  if (t.status === "running")
    return (
      <span className="tag bg-carbon-blue/10 text-carbon-blue">
        <span className="live-dot mr-1.5 inline-block w-1.5 h-1.5 rounded-full bg-carbon-blue" />
        LIVE
      </span>
    );
  if (t.status === "error")
    return <span className="tag bg-carbon-red/10 text-carbon-red">ERROR</span>;
  if (t.status === "done") {
    const passed = verifyPassed(t);
    return passed ? (
      <span className="tag bg-carbon-green/10 text-carbon-green">✓ PASS</span>
    ) : (
      <span className="tag bg-carbon-yellow/20 text-[#8a6d00]">DONE</span>
    );
  }
  return <span className="tag bg-carbon-bg text-carbon-subtle">idle</span>;
}

export default function Leaderboard({ tools, selected, onSelect }) {
  const entries = Object.entries(tools);
  const ranked = [...entries].sort((a, b) => {
    const ka = sortKey(a[1]);
    const kb = sortKey(b[1]);
    return ka[0] - kb[0] || ka[1] - kb[1];
  });

  return (
    <div className="panel overflow-hidden">
      <div className="grid grid-cols-[40px_1.4fr_1fr_0.9fr_0.9fr_0.8fr] items-center px-5 py-3 text-[11px] uppercase tracking-wider text-carbon-subtle border-b border-carbon-border bg-carbon-bg/40">
        <div>#</div>
        <div>Agent</div>
        <div>Activity</div>
        <div className="text-right">Tokens</div>
        <div className="text-right">Cost</div>
        <div className="text-right">Time</div>
      </div>

      {ranked.map(([tool, t], i) => {
        const cost = t.row ? t.row.usd_cost : t.liveUsd;
        const tok = t.row
          ? (t.row.input_tokens || 0) + (t.row.output_tokens || 0)
          : t.liveTokens;
        const isWinner = i === 0 && t.status === "done";
        const isSel = tool === selected;
        return (
          <div
            key={tool}
            onClick={() => onSelect && onSelect(tool)}
            title={onSelect ? "Click to standardize the projection on this agent" : undefined}
            style={isSel ? { boxShadow: "inset 3px 0 0 #0f62fe" } : undefined}
            className={`leader-row grid grid-cols-[40px_1.4fr_1fr_0.9fr_0.9fr_0.8fr] items-center px-5 py-4 border-b border-carbon-border last:border-b-0 ${
              onSelect ? "cursor-pointer" : ""
            } ${isSel ? "bg-carbon-blue/[0.045]" : "hover:bg-carbon-bg/60"}`}
          >
            <div className="metric-num text-lg font-semibold text-carbon-subtle">
              {i + 1}
            </div>
            <div className="flex items-center gap-2.5 min-w-0">
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ background: TOOL_COLOR[tool] }}
              />
              <span className="font-medium truncate">{TOOL_LABEL[tool] || tool}</span>
              <StatusPill t={t} />
              {t.status === "done" && t.row?.extras?.run_mode === "live" && (
                <span className="tag bg-carbon-blue/10 text-carbon-blue">● LIVE</span>
              )}
              {t.status === "done" && t.row?.extras?.run_mode && t.row.extras.run_mode !== "live" && (
                <span className="tag bg-carbon-bg text-carbon-subtle">recorded</span>
              )}
            </div>
            <div className="text-sm text-carbon-subtle truncate font-mono">
              {t.status === "running" ? t.lastActivity || "working…" : t.row?.model || "—"}
            </div>
            <div className="metric-num text-right text-sm">
              {tok != null ? tokens(tok) : "—"}
            </div>
            <div
              className={`metric-num text-right font-semibold ${
                t.status === "running" && cost == null ? "text-carbon-subtle" : ""
              }`}
            >
              {cost != null ? usd(cost) : t.status === "running" ? "…" : "—"}
            </div>
            <div className="metric-num text-right text-sm text-carbon-subtle">
              {secs(t.elapsedMs)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
