"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamUrl } from "./api";
import { TOOLS } from "./format";

function blankTool() {
  return {
    status: "idle", // idle | running | done | error
    startedAt: null,
    elapsedMs: 0,
    lines: 0,
    lastActivity: "",
    liveUsd: null, // only Claude reports USD mid-stream; others true-up on done
    liveTokens: null,
    row: null, // authoritative parsed result from the `done` event
    error: null,
  };
}

// Best-effort sniff of a streamed JSONL line for live tokens / USD. Authoritative
// numbers always come from the `done` event; this is just for the live feel.
function sniff(tool, line) {
  let obj;
  try {
    obj = JSON.parse(line);
  } catch {
    return null;
  }
  const out = {};
  // A short human label of what's happening, for the activity ticker.
  // Live Claude emits assistant events whose message.content[] carries
  // tool_use blocks with a `name` (Read/Edit/Bash/…); recordings carry an
  // explicit activity_label. Fall back to the raw event type.
  let liveToolName = null;
  const content = obj.message && obj.message.content;
  if (Array.isArray(content)) {
    const tu = content.find((c) => c && c.type === "tool_use" && c.name);
    if (tu) {
      liveToolName = tu.name;
      const input = tu.input || {};
      const target = input.file_path || input.path || input.command || input.pattern;
      if (target) {
        const short = String(target).split("/").pop().slice(0, 40);
        liveToolName = `${tu.name} · ${short}`;
      }
    }
  }
  const label =
    obj.activity_label ||
    (obj.data && obj.data.activity_label) ||
    liveToolName ||
    (obj.tool_name && obj.tool_name !== "attempt_completion" ? obj.tool_name : null);
  if (label) {
    out.activity = String(label);
  } else {
    const t = obj.type || obj.subtype;
    if (t) out.activity = String(t).replace(/[._]/g, " ");
  }
  // Claude reports real USD directly on its result event.
  if (tool === "claude" && obj.total_cost_usd != null) out.usd = obj.total_cost_usd;
  // Tokens, where each tool exposes them.
  const usage = obj.usage || (obj.stats && obj.stats.models && obj.stats.models.premium && obj.stats.models.premium.tokens);
  if (usage) {
    const inTok =
      (usage.input_tokens || usage.prompt || 0) +
      (usage.cache_creation_input_tokens || 0) +
      (usage.cache_read_input_tokens || usage.cached || 0);
    const outTok = usage.output_tokens || usage.candidates || 0;
    if (inTok || outTok) out.tokens = inTok + outTok;
  }
  return out;
}

export function useRun() {
  const [runId, setRunId] = useState(null);
  const [runMode, setRunMode] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | running | complete
  const [tools, setTools] = useState(() =>
    Object.fromEntries(TOOLS.map((t) => [t, blankTool()]))
  );
  const esRef = useRef([]);
  const timerRef = useRef(null);

  const patch = useCallback((tool, fields) => {
    setTools((prev) => ({ ...prev, [tool]: { ...prev[tool], ...fields } }));
  }, []);

  // Tick elapsed timers for running tools.
  useEffect(() => {
    if (phase !== "running") return;
    timerRef.current = setInterval(() => {
      setTools((prev) => {
        const next = { ...prev };
        let changed = false;
        for (const t of TOOLS) {
          if (next[t].status === "running" && next[t].startedAt) {
            next[t] = { ...next[t], elapsedMs: Date.now() - next[t].startedAt };
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, 100);
    return () => clearInterval(timerRef.current);
  }, [phase]);

  const cleanup = useCallback(() => {
    esRef.current.forEach((es) => es.close());
    esRef.current = [];
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(
    async ({ scenario_id, run_mode = "simulated", department_id, submitter, tools: toolList = TOOLS }) => {
      cleanup();
      const fresh = Object.fromEntries(toolList.map((t) => [t, blankTool()]));
      setTools(fresh);
      setPhase("running");

      const resp = await api.startRun({ scenario_id, run_mode, department_id, submitter, tools: toolList });
      setRunId(resp.run_id);
      setRunMode(resp.run_mode);

      const t0 = Date.now();
      toolList.forEach((tool) => patch(tool, { status: "running", startedAt: t0 }));

      let remaining = toolList.length;
      toolList.forEach((tool) => {
        const es = new EventSource(streamUrl(resp.run_id, tool));
        esRef.current.push(es);

        es.addEventListener("stdout", (e) => {
          const s = sniff(tool, e.data);
          setTools((prev) => {
            const cur = prev[tool];
            const upd = { lines: cur.lines + 1 };
            if (s) {
              if (s.activity) upd.lastActivity = s.activity;
              if (s.usd != null) upd.liveUsd = s.usd;
              if (s.tokens != null) upd.liveTokens = s.tokens;
            }
            return { ...prev, [tool]: { ...cur, ...upd } };
          });
        });

        es.addEventListener("done", (e) => {
          let row = null;
          try {
            row = JSON.parse(e.data);
          } catch {
            /* keep null */
          }
          patch(tool, {
            status: row && row.error ? "error" : "done",
            row,
            error: row ? row.error : null,
            elapsedMs: row && row.wall_clock_ms ? row.wall_clock_ms : Date.now() - t0,
          });
          es.close();
          remaining -= 1;
          if (remaining <= 0) setPhase("complete");
        });

        es.onerror = () => {
          // EventSource auto-retries; if the run is already complete, close.
          if (es.readyState === 2) {
            remaining -= 1;
            if (remaining <= 0) setPhase("complete");
          }
        };
      });

      return resp;
    },
    [cleanup, patch]
  );

  return { runId, runMode, phase, tools, start };
}
