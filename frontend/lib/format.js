export const TOOLS = ["bob", "claude", "copilot"];

export const TOOL_LABEL = { bob: "IBM BOB", claude: "Claude", copilot: "Copilot" };

// Each agent gets a brand-ish accent for quick visual ID.
export const TOOL_COLOR = {
  bob: "#0f62fe", // IBM blue
  claude: "#d97757", // Anthropic clay
  copilot: "#6f42c1", // GitHub purple
};

export function usd(n) {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  if (v === 0) return "$0.00";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  if (v < 1) return `$${v.toFixed(3)}`;
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Whole-dollar formatting for big executive figures ($338,100).
export function usd0(n) {
  if (n === null || n === undefined) return "—";
  return `$${Math.round(Number(n)).toLocaleString()}`;
}

// Compact ($1.2M, $897K) for chart axes and tight spaces.
export function usdCompact(n) {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `$${Math.round(v / 1e3)}K`;
  return `$${Math.round(v)}`;
}

export function int(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString();
}

export function tokens(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString();
}

export function secs(ms) {
  if (ms === null || ms === undefined) return "—";
  return `${(ms / 1000).toFixed(1)}s`;
}

export function pct(x) {
  if (x === null || x === undefined) return "—";
  return `${(x * 100).toFixed(0)}%`;
}
