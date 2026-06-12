"use client";
import { useEffect, useState } from "react";
import { api, API_BASE } from "../lib/api";
import { TOOL_LABEL, TOOL_COLOR, usd, int, secs, pct } from "../lib/format";

// The V1 deliverable proof: every run lands in SQLite, and the per-scenario
// per-agent averages below are exactly the dataset Planning Analytics
// ingests to model projections.

function timeAgo(iso) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export default function RunsDatabase({ refreshKey, scenarioTitles = {} }) {
  const [avgs, setAvgs] = useState([]);
  const [runs, setRuns] = useState([]);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    api.averages().then(setAvgs).catch(() => {});
    api.runs().then(setRuns).catch(() => {});
  }, [refreshKey]);

  const visibleRuns = showAll ? runs : runs.slice(0, 8);

  return (
    <section>
      <div className="flex items-end justify-between flex-wrap gap-2 mb-1">
        <div>
          <h2 className="text-base font-semibold">Runs Database</h2>
          <p className="text-sm text-carbon-subtle">
            Every run is stored in SQLite — these aggregates are the dataset Planning Analytics ingests.
          </p>
        </div>
        <a href={`${API_BASE}/api/export/runs.csv`} className="btn-ghost text-sm" download>
          ⤓ Export CSV
        </a>
      </div>

      {/* Averages per scenario × agent */}
      <div className="panel overflow-hidden mt-3">
        <div className="grid grid-cols-[1.6fr_1fr_0.6fr_0.8fr_0.9fr_0.8fr_0.7fr] px-5 py-3 text-[11px] uppercase tracking-wider text-carbon-subtle border-b border-carbon-border bg-carbon-bg/40">
          <div>Scenario</div>
          <div>Agent</div>
          <div className="text-right">Runs</div>
          <div className="text-right">Avg cost</div>
          <div className="text-right">Avg tokens</div>
          <div className="text-right">Avg time</div>
          <div className="text-right">Pass</div>
        </div>
        {avgs.map((a) => (
          <div key={`${a.scenario_id}-${a.tool}`}
            className="grid grid-cols-[1.6fr_1fr_0.6fr_0.8fr_0.9fr_0.8fr_0.7fr] items-center px-5 py-3 border-b border-carbon-border last:border-b-0 text-sm">
            <div className="truncate text-carbon-subtle">{scenarioTitles[a.scenario_id] || a.scenario_id}</div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ background: TOOL_COLOR[a.tool] }} />
              {TOOL_LABEL[a.tool] || a.tool}
            </div>
            <div className="metric-num text-right">{a.runs}</div>
            <div className="metric-num text-right font-semibold">{usd(a.avg_usd)}</div>
            <div className="metric-num text-right">{int(a.avg_tokens)}</div>
            <div className="metric-num text-right">{secs(a.avg_duration_ms)}</div>
            <div className={`metric-num text-right ${a.pass_rate >= 1 ? "text-carbon-green" : a.pass_rate > 0 ? "text-[#8a6d00]" : "text-carbon-subtle"}`}>
              {pct(a.pass_rate)}
            </div>
          </div>
        ))}
        {avgs.length === 0 && <div className="px-5 py-4 text-sm text-carbon-subtle">No runs stored yet.</div>}
      </div>

      {/* Recent raw runs */}
      <div className="panel overflow-hidden mt-3">
        <div className="grid grid-cols-[0.8fr_1.4fr_1fr_0.8fr_0.9fr_0.8fr_0.7fr] px-5 py-3 text-[11px] uppercase tracking-wider text-carbon-subtle border-b border-carbon-border bg-carbon-bg/40">
          <div>When</div>
          <div>Scenario</div>
          <div>Agent</div>
          <div>Mode</div>
          <div className="text-right">Tokens</div>
          <div className="text-right">Cost</div>
          <div className="text-right">Time</div>
        </div>
        {visibleRuns.map((r) => (
          <div key={r.id}
            className="grid grid-cols-[0.8fr_1.4fr_1fr_0.8fr_0.9fr_0.8fr_0.7fr] items-center px-5 py-2.5 border-b border-carbon-border last:border-b-0 text-sm">
            <div className="text-carbon-subtle text-xs">{timeAgo(r.started_at)}</div>
            <div className="truncate text-carbon-subtle">{scenarioTitles[r.scenario_id] || r.scenario_id}</div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ background: TOOL_COLOR[r.tool] }} />
              {TOOL_LABEL[r.tool] || r.tool}
            </div>
            <div>
              {r.run_mode === "live"
                ? <span className="tag bg-carbon-blue/10 text-carbon-blue">● live</span>
                : <span className="tag bg-carbon-bg text-carbon-subtle">{r.run_mode || "—"}</span>}
            </div>
            <div className="metric-num text-right">{int((r.input_tokens || 0) + (r.output_tokens || 0))}</div>
            <div className="metric-num text-right font-medium">{usd(r.usd_cost)}</div>
            <div className="metric-num text-right text-carbon-subtle">{secs(r.duration_ms ?? r.wall_clock_ms)}</div>
          </div>
        ))}
        {runs.length > 8 && (
          <button className="w-full px-5 py-2.5 text-sm text-carbon-blue hover:bg-carbon-bg/50 transition-colors"
            onClick={() => setShowAll((s) => !s)}>
            {showAll ? "Show fewer" : `Show all ${runs.length} runs`}
          </button>
        )}
      </div>
    </section>
  );
}
