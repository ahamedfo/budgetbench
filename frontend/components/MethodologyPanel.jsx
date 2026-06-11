"use client";
import { useState } from "react";

// Transparency is the credibility anchor for a sales tool: show exactly how
// each agent's USD figure is derived, including the one estimate.
const ROWS = [
  {
    tool: "IBM BOB",
    basis: "Bobcoins × USD/coin",
    detail:
      "BOB reports session cost in Bobcoins. Converted at the configured rate (default $0.50/coin, env BOB_USD_PER_BOBCOIN). Tokens read from BOB's own usage stats.",
    estimated: false,
  },
  {
    tool: "Claude",
    basis: "Reported USD (actual)",
    detail:
      "Claude Code reports total_cost_usd directly from the API. No estimation — this is the billed amount.",
    estimated: false,
  },
  {
    tool: "Copilot",
    basis: "Tokens × public list price",
    detail:
      "Copilot's CLI surfaces output tokens but not input tokens, so input is estimated (chars ÷ 4 + system overhead). Cost = tokens × the model's public per-MTok rate.",
    estimated: true,
  },
];

export default function MethodologyPanel() {
  const [open, setOpen] = useState(false);
  return (
    <section className="panel">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-sm font-medium">How we calculate cost</span>
        <span className="text-carbon-subtle text-sm">{open ? "–" : "+"}</span>
      </button>
      {open && (
        <div className="border-t border-carbon-border divide-y divide-carbon-border">
          {ROWS.map((r) => (
            <div key={r.tool} className="px-4 py-3">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="font-medium text-sm">{r.tool}</span>
                <span className="text-xs text-carbon-subtle">— {r.basis}</span>
                {r.estimated && (
                  <span className="tag bg-carbon-yellow/20 text-[#8a6d00] ml-auto">
                    partly estimated
                  </span>
                )}
              </div>
              <p className="text-sm text-carbon-subtle">{r.detail}</p>
            </div>
          ))}
          <p className="px-4 py-3 text-xs text-carbon-subtle">
            All figures use each provider's public list prices. Replay/simulated runs use real
            telemetry recorded from prior live runs.
          </p>
        </div>
      )}
    </section>
  );
}
