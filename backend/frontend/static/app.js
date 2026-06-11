// Bake-off harness — client renderer.
//
// All three tools (Bob / Claude / Copilot) emit different raw JSONL.
// We normalize each into a common event shape, then a single renderer
// routes events into two areas per column:
//
//   Background  — tool calls, thinking, system events (collapsible)
//   Answer      — the model's actual reply text + final structured summary

const TOOLS = ["bob", "claude", "copilot"];

// During the run, every tool's running text is routed to the Background
// section so the Answer section stays clean (just a "waiting…"
// placeholder). When the tool finishes, the Answer section is replaced
// with collapsible structured cards parsed from the model's final
// reply (## VULNERABILITIES FOUND / FIXES APPLIED / ...).
// (Previously Claude/Copilot's intermediate narration was leaking into
// Answer, which broke the "show only the final answer" UX.)
const TEXT_GOES_TO_ANSWER = { bob: false, claude: false, copilot: false };

let activeRunId = null;
let activeDisplayOverrides = {};   // tool → display_model name (e.g. copilot → "claude-sonnet-4.6")
const timers   = {};
const state    = {};   // per-tool runtime state

const $  = (sel, root = document) => root.querySelector(sel);
const colEl = (t) => $(`.col[data-tool="${t}"]`);
const role  = (t, name) => colEl(t).querySelector(`[data-role="${name}"]`);

function newColState() {
  return {
    bgCount: 0,
    pendingToolCalls: {}, // toolId → <details> in the bg-stream
    thinkingEl: null,
    currentAnswerBubble: null,
    finalText: null,
    // Bob-specific: state machine for stripping <thinking>...</thinking>
    // from streamed narration. Bob emits these tags as part of normal
    // text deltas (e.g. "<thinking>**...") so we can't just match on
    // standalone deltas — we need to track open/close across the stream.
    inThinking: false,
    thinkingCard: null,
    thinkingPre: null,
  };
}

const VERIF_PLACEHOLDER = `<div class="verif-grid">
  <div class="k">Tests</div>             <div class="v dim">—</div>
  <div class="k">New tests added</div>   <div class="v dim">—</div>
  <div class="k">Semgrep</div>           <div class="v dim">—</div>
  <div class="k">Forbidden patterns</div><div class="v dim">—</div>
  <div class="k">Issue resolved</div>    <div class="v dim">—</div>
  <div class="k">Lines changed</div>     <div class="v dim">—</div>
  <div class="k">Files modified</div>    <div class="v dim">—</div>
</div>`;

// Returns null if the run is clean, otherwise a structured description
// of what went wrong (used to drive status pill, warn badge, and an
// in-Answer notice). Catches the common Copilot session.error types
// in addition to generic harness errors.
function parseColumnError(row) {
  const raw = (row && row.error) || "";
  if (!raw.trim()) return null;
  const lower = raw.toLowerCase();
  if (/rate_limit|rate[- ]?limited|429/.test(lower)) {
    return {
      kind: "rate_limit",
      statusLabel: "rate limited",
      title: "Rate limit hit",
      body: "The provider rate-limited this tool. Wait for the quota window "
          + "to reset (~3h on Copilot Free), or upgrade your plan.\n\n"
          + raw,
    };
  }
  if (/capi|connection error|network|connection refused|timeout|timed out/i.test(raw)) {
    return {
      kind: "connection",
      statusLabel: "API error",
      title: "Connection error",
      body: "The tool couldn't reach its model provider after retries. "
          + "This is usually a transient upstream issue — try again in a "
          + "minute.\n\n" + raw,
    };
  }
  if (/parse_error/i.test(raw)) {
    return {
      kind: "parse_error",
      statusLabel: "parse error",
      title: "Could not parse tool output",
      body: "The tool ran but its output didn't match an expected shape. "
          + "Details: " + raw,
    };
  }
  return {
    kind: "other",
    statusLabel: "failed",
    title: "Run failed",
    body: raw,
  };
}

function resetCol(t) {
  role(t, "bg-stream").innerHTML = "";
  role(t, "answer-stream").innerHTML = '<div class="answer-placeholder" data-role="answer-placeholder">waiting…</div>';
  role(t, "verification-body").innerHTML = VERIF_PLACEHOLDER;
  // Clear any leftover warning indicator from a previous run
  const wb = role(t, "warn-badge");
  if (wb) { wb.hidden = true; wb.title = ""; }
  role(t, "cost").textContent = "—";
  role(t, "tokens").textContent = "—";
  role(t, "model").textContent = "—";
  role(t, "timer").textContent = "0.0s";
  setStatus(t, "idle", "idle");
  // Re-open background section
  setBgState(t, "open");
  state[t] = newColState();
}

function setBgState(t, s) {
  const bg = role(t, "bg-section");
  if (bg) bg.setAttribute("data-state", s);
}
function toggleBgState(t) {
  const bg = role(t, "bg-section");
  if (!bg) return;
  bg.setAttribute("data-state",
    bg.getAttribute("data-state") === "open" ? "closed" : "open");
}

function setStatus(t, label, cls) {
  const el = role(t, "status");
  el.textContent = label;
  el.className = `status ${cls}`;
}

function startTimer(t) {
  const start = performance.now();
  timers[t] = setInterval(() => {
    role(t, "timer").textContent = `${((performance.now() - start) / 1000).toFixed(1)}s`;
  }, 100);
}
function stopTimer(t) { clearInterval(timers[t]); timers[t] = null; }

// ─────────────── Normalizers ───────────────
// Common event shapes:
//   { kind: "system",      text }
//   { kind: "thinking",    on: bool }
//   { kind: "turn_start" }
//   { kind: "text_delta",  text }      // append to current answer bubble
//   { kind: "text",        text }      // full text block, new answer bubble
//   { kind: "tool_call",   toolId, name, args }
//   { kind: "tool_result", toolId, success, output }
//   { kind: "final",       text }      // structured final response

function normalize(tool, raw) {
  let evt;
  try { evt = JSON.parse(raw); } catch { return null; }
  if (tool === "bob")     return normBob(evt);
  if (tool === "claude")  return normClaude(evt);
  if (tool === "copilot") return normCopilot(evt);
  return null;
}

const asArray = (x) => (x == null ? [] : Array.isArray(x) ? x : [x]);

function normBob(e) {
  switch (e.type) {
    case "init":
      return [{ kind: "system", text: `Started · ${e.model || "?"}` }];
    case "message": {
      if (e.role !== "assistant" || !e.delta) return null;
      const c = e.content;
      if (c == null) return null;
      // Skip the "[using tool ... | Cost: ...]" status echoes — we
      // already render proper tool_use cards from the structured events.
      if (typeof c === "string" && c.trimStart().startsWith("[using tool")) return null;
      // Stream a "text_delta" — the renderer (renderBobTextDelta) is
      // responsible for filtering <thinking>...</thinking> regions and
      // for preserving whitespace-only deltas (Bob uses single-space
      // deltas as word separators).
      return [{ kind: "text_delta", text: c }];
    }
    case "tool_use":
      if (e.tool_name === "attempt_completion") {
        return [{ kind: "final", text: (e.parameters || {}).result || "" }];
      }
      return [{ kind: "tool_call", toolId: e.tool_id, name: e.tool_name, args: e.parameters }];
    case "tool_result":
      return [{ kind: "tool_result", toolId: e.tool_id, success: e.status === "success", output: e.output }];
    case "result":
      return [{ kind: "system", text: "Finished" }];
  }
  return null;
}

function normClaude(e) {
  switch (e.type) {
    case "system":
      if (e.subtype === "init") return [{ kind: "system", text: `Started · ${e.model || "?"}` }];
      return null;
    case "assistant": {
      const msg = e.message || {};
      const out = [{ kind: "turn_start" }];
      for (const part of msg.content || []) {
        if (part.type === "text")     out.push({ kind: "text", text: part.text || "" });
        else if (part.type === "tool_use") out.push({ kind: "tool_call", toolId: part.id, name: part.name, args: part.input });
        else if (part.type === "thinking") out.push({ kind: "thinking", on: true });
      }
      return out;
    }
    case "user": {
      const msg = e.message || {};
      const out = [];
      for (const part of msg.content || []) {
        if (part.type === "tool_result") {
          const text = Array.isArray(part.content)
            ? part.content.map(p => p.text || "").join("\n")
            : String(part.content || "");
          out.push({ kind: "tool_result", toolId: part.tool_use_id, success: !part.is_error, output: text });
        }
      }
      return out;
    }
    case "result":
      return [{ kind: "system", text: "Finished" }];
  }
  return null;
}

function normCopilot(e) {
  switch (e.type) {
    case "session.tools_updated": {
      const override = activeDisplayOverrides && activeDisplayOverrides.copilot;
      const m = override || (e.data && e.data.model) || "?";
      return [{ kind: "system", text: `Model: ${m}` }];
    }
    case "model.call_failure": {
      // Surface a subtle line in Background for each retry, so the user
      // can tell the column isn't hung — Copilot is silently retrying.
      const d = e.data || {};
      let reason = "API call failed";
      const msg = d.errorMessage || "";
      const m = msg.match(/"message"\s*:\s*"([^"]+)"/);
      if (m) reason = m[1];
      else if (d.statusCode) reason = `HTTP ${d.statusCode}`;
      const shortened = reason.length > 80 ? reason.slice(0, 80) + "…" : reason;
      return [{ kind: "system", text: `⚠ API retry — ${shortened}` }];
    }
    case "assistant.turn_start":  return [{ kind: "turn_start" }];
    case "assistant.reasoning_delta":  return [{ kind: "thinking", on: true  }];
    case "assistant.message_start":    return [{ kind: "thinking", on: false }];
    case "assistant.message_delta":
      return [{ kind: "text_delta", text: (e.data && e.data.deltaContent) || "" }];
    case "assistant.message": {
      const tools = ((e.data && e.data.toolRequests) || []).map(t => ({
        kind: "tool_call", toolId: t.toolCallId, name: t.name, args: t.arguments,
      }));
      return tools.length ? tools : null;
    }
    case "tool.execution_start":
      return [{ kind: "tool_call",
                toolId: e.data && e.data.toolCallId,
                name: (e.data && e.data.toolName) || "tool",
                args: e.data && e.data.arguments }];
    case "tool.execution_complete": {
      const d = e.data || {};
      return [{ kind: "tool_result",
                toolId: d.toolCallId,
                success: !d.error && d.status !== "error",
                output: d.result || d.output || d.error || "" }];
    }
    case "result":
      return [{ kind: "system", text: "Finished" }];
  }
  return null;
}

// ─────────────── Renderer ───────────────

function render(tool, evt) {
  if (!evt) return;
  for (const ev of asArray(evt)) {
    switch (ev.kind) {
      case "system":      bgSystem(tool, ev.text); break;
      case "thinking":    bgThinking(tool, ev.on); break;
      case "turn_start":  onTurnStart(tool); break;
      case "tool_call":   bgToolCall(tool, ev); break;
      case "tool_result": bgToolResult(tool, ev); break;
      case "text_delta":
        if (TEXT_GOES_TO_ANSWER[tool]) answerTextDelta(tool, ev.text);
        else                            bgText(tool, ev.text);
        break;
      case "text":
        if (TEXT_GOES_TO_ANSWER[tool]) answerTextBlock(tool, ev.text);
        else                            bgText(tool, ev.text);
        break;
      case "final":
        // Don't render immediately — save for onDone so all three tools'
        // Answer sections behave identically (filled in at completion).
        state[tool].finalText = ev.text;
        break;
    }
  }
}

// ── Background section ──

function bgAppend(tool, node) {
  const stream = role(tool, "bg-stream");
  const near = (stream.scrollHeight - stream.scrollTop - stream.clientHeight) < 80;
  stream.appendChild(node);
  if (near) stream.scrollTop = stream.scrollHeight;
}

function bgSystem(tool, text) {
  const d = document.createElement("div");
  d.className = "sys";
  d.textContent = text;
  bgAppend(tool, d);
}

function bgThinking(tool, on) {
  const st = state[tool];
  if (on) {
    if (st.thinkingEl) return;
    const d = document.createElement("div");
    d.className = "thinking";
    d.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span> thinking';
    st.thinkingEl = d;
    bgAppend(tool, d);
  } else if (st.thinkingEl) {
    st.thinkingEl.remove();
    st.thinkingEl = null;
  }
}

function bgText(tool, text) {
  // For Bob: assistant streaming text is reasoning/narration, not the
  // answer. We strip <thinking>...</thinking> regions into their own
  // collapsible block, and feed everything else into a narration line.
  // Whitespace-only deltas matter — Bob emits a single " " as a word
  // separator, so we MUST NOT drop them.
  if (text == null || text === "") return;
  const st = state[tool];

  // Walk the delta consuming <thinking> / </thinking> markers, routing
  // each piece to either the narration or the current thinking block.
  let remaining = text;
  while (remaining.length > 0) {
    if (!st.inThinking) {
      const i = remaining.indexOf("<thinking>");
      if (i < 0) {
        appendNarration(tool, remaining);
        break;
      }
      if (i > 0) appendNarration(tool, remaining.slice(0, i));
      remaining = remaining.slice(i + "<thinking>".length);
      st.inThinking = true;
      // close narration so subsequent narration creates a fresh line
      st._narrEl = null;
      openThinkingBlock(tool);
    } else {
      const j = remaining.indexOf("</thinking>");
      if (j < 0) {
        appendToThinkingBlock(tool, remaining);
        break;
      }
      if (j > 0) appendToThinkingBlock(tool, remaining.slice(0, j));
      remaining = remaining.slice(j + "</thinking>".length);
      st.inThinking = false;
      closeThinkingBlock(tool);
    }
  }
}

function appendNarration(tool, text) {
  if (!text) return;
  const st = state[tool];
  const stream = role(tool, "bg-stream");
  if (st._narrEl && st._narrEl.parentNode === stream) {
    // Appending to an existing narration block — keep all whitespace
    // (Bob streams single-space deltas as word separators).
    st._narrEl.textContent += text;
    if ((stream.scrollHeight - stream.scrollTop - stream.clientHeight) < 200)
      stream.scrollTop = stream.scrollHeight;
    return;
  }
  // Starting a NEW narration block — skip if it's only whitespace, so
  // we don't leave a hollow gap between a thinking card and the next
  // tool call.
  if (!text.trim()) return;
  const d = document.createElement("div");
  d.className = "narration";
  d.textContent = text;
  st._narrEl = d;
  bgAppend(tool, d);
}

function openThinkingBlock(tool) {
  const st = state[tool];
  if (st.thinkingCard) return;
  // Use the exact same .tool-card shell as real tool calls so it looks
  // consistent — just with a 💭 icon and "thinking" name.
  const card = document.createElement("details");
  card.className = "tool-card thinking-card";

  const sum = document.createElement("summary");
  const icon = document.createElement("span");
  icon.className = "tool-icon";
  icon.textContent = "💭";
  const name = document.createElement("span");
  name.className = "tool-name";
  name.textContent = "thinking";
  const preview = document.createElement("span");
  preview.className = "tool-preview";
  const status = document.createElement("span");
  status.className = "tool-status running";
  status.textContent = "running";
  sum.append(icon, name, preview, status);

  const body = document.createElement("div");
  body.className = "tool-body";
  const pre = document.createElement("pre");
  pre.className = "tool-output";
  body.appendChild(pre);

  card.append(sum, body);
  st.thinkingCard = card;
  st.thinkingPre = pre;
  st.thinkingPreview = preview;
  bgAppend(tool, card);
}
function appendToThinkingBlock(tool, text) {
  const st = state[tool];
  if (!st.thinkingPre) openThinkingBlock(tool);
  st.thinkingPre.textContent += text;
  // Surface the first line of thinking as the preview (so the closed
  // card hints at what was thought about, like real tool cards do).
  if (st.thinkingPreview && !st.thinkingPreview.textContent) {
    const firstLine = (st.thinkingPre.textContent.split(/\n/, 1)[0] || "").trim();
    if (firstLine) st.thinkingPreview.textContent = truncate(firstLine.replace(/\s+/g, " "), 100);
  }
}
function closeThinkingBlock(tool) {
  const st = state[tool];
  if (st.thinkingCard) {
    const sEl = st.thinkingCard.querySelector(".tool-status");
    if (sEl) { sEl.className = "tool-status ok"; sEl.textContent = "done"; }
  }
  st.thinkingCard = null;
  st.thinkingPre = null;
  st.thinkingPreview = null;
}

function bgToolCall(tool, ev) {
  const card = document.createElement("details");
  card.className = "tool-card";
  const summary = document.createElement("summary");

  const icon = document.createElement("span");
  icon.className = "tool-icon";
  icon.textContent = pickToolIcon(ev.name);

  const name = document.createElement("span");
  name.className = "tool-name";
  name.textContent = ev.name || "tool";

  const preview = document.createElement("span");
  preview.className = "tool-preview";
  preview.textContent = oneLineArgPreview(ev.name, ev.args);

  const status = document.createElement("span");
  status.className = "tool-status running";
  status.textContent = "running";

  summary.append(icon, name, preview, status);
  card.appendChild(summary);

  const body = document.createElement("div");
  body.className = "tool-body";
  if (ev.args !== undefined && ev.args !== null) {
    const argsEl = document.createElement("pre");
    argsEl.className = "tool-args";
    argsEl.textContent = prettyJson(ev.args);
    body.appendChild(argsEl);
  }
  card.appendChild(body);

  if (ev.toolId) state[tool].pendingToolCalls[ev.toolId] = card;
  // Reset the narration anchor — next narration delta starts a fresh line
  // (so we don't keep appending to a stale block after a tool call).
  state[tool]._narrEl = null;
  bgAppend(tool, card);
}

function bgToolResult(tool, ev) {
  const st = state[tool];
  const card = ev.toolId ? st.pendingToolCalls[ev.toolId] : null;
  const isError = ev.success === false;
  const txt = typeof ev.output === "string" ? ev.output : prettyJson(ev.output);

  if (card) {
    const sEl = card.querySelector(".tool-status");
    if (sEl) {
      sEl.className = `tool-status ${isError ? "error" : "ok"}`;
      sEl.textContent = isError ? "error" : "ok";
    }
    const body = card.querySelector(".tool-body");
    const out = document.createElement("pre");
    out.className = `tool-output ${isError ? "error" : ""}`;
    out.textContent = truncate(txt, 4000);
    body.appendChild(out);
    delete st.pendingToolCalls[ev.toolId];
  } else {
    const d = document.createElement("div");
    d.className = `sys ${isError ? "error" : ""}`;
    d.textContent = `↳ ${truncate(txt, 200)}`;
    bgAppend(tool, d);
  }
}

// ── Answer section ──

function clearAnswerPlaceholder(tool) {
  const ph = role(tool, "answer-stream").querySelector('[data-role="answer-placeholder"]');
  if (ph) ph.remove();
}

function onTurnStart(tool) {
  // Close the current answer bubble so the next text starts fresh.
  state[tool].currentAnswerBubble = null;
  bgThinking(tool, false);
}

function answerTextDelta(tool, text) {
  if (!text) return;
  clearAnswerPlaceholder(tool);
  const stream = role(tool, "answer-stream");
  const st = state[tool];
  if (!st.currentAnswerBubble) {
    st.currentAnswerBubble = document.createElement("div");
    st.currentAnswerBubble.className = "ans-bubble";
    stream.appendChild(st.currentAnswerBubble);
  }
  st.currentAnswerBubble.textContent += text;
  if ((stream.scrollHeight - stream.scrollTop - stream.clientHeight) < 200)
    stream.scrollTop = stream.scrollHeight;
}

function answerTextBlock(tool, text) {
  if (!text || !text.trim()) return;
  clearAnswerPlaceholder(tool);
  const d = document.createElement("div");
  d.className = "ans-bubble";
  d.textContent = text;
  role(tool, "answer-stream").appendChild(d);
  state[tool].currentAnswerBubble = null;  // next text → new bubble
}

function renderFinalIntoAnswer(tool, text) {
  // For Bob: parse the ## sections from the attempt_completion result
  // and render as collapsible cards in the answer section. This is the
  // tool's real answer, so we replace any narration that came before it.
  clearAnswerPlaceholder(tool);
  const stream = role(tool, "answer-stream");
  stream.innerHTML = "";

  const sections = extractMarkdownSections(text);
  if (sections.length === 0) {
    const pre = document.createElement("pre");
    pre.className = "ans-raw";
    pre.textContent = text;
    stream.appendChild(pre);
    return;
  }
  for (const [title, body] of sections) {
    const card = document.createElement("details");
    card.className = "sec-card";
    card.open = true;
    const sum = document.createElement("summary");
    sum.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = body;
    card.append(sum, pre);
    stream.appendChild(card);
  }
}

// "## TITLE\n\nbody\n\n## TITLE2\n\nbody" → [[title, body], ...]
function extractMarkdownSections(text) {
  if (!text) return [];
  const out = [];
  const re = /^#{1,4}\s+([^\n]+?)\s*$/gm;
  const indices = [];
  let m;
  while ((m = re.exec(text)) !== null) {
    indices.push({ title: m[1].trim(), start: m.index + m[0].length });
  }
  for (let i = 0; i < indices.length; i++) {
    const end = i + 1 < indices.length ? indices[i + 1].start - 1 : text.length;
    // Trim the header line of the next section out of `end` calc
    const nextHeaderIdx = i + 1 < indices.length ? text.lastIndexOf("\n", indices[i + 1].start - 1) : end;
    const sliceEnd = i + 1 < indices.length ? nextHeaderIdx : text.length;
    const body = text.slice(indices[i].start, sliceEnd).trim();
    out.push([indices[i].title, body]);
  }
  return out;
}

// ─────────────── Done / footer / comparison ───────────────

function onDone(tool, dataStr) {
  stopTimer(tool);
  bgThinking(tool, false);
  // If Bob ended mid-thinking (no closing tag), close out the block
  if (state[tool] && state[tool].inThinking) {
    closeThinkingBlock(tool);
    state[tool].inThinking = false;
  }

  let row;
  try { row = JSON.parse(dataStr); } catch { return; }
  if (!row || !row.tool) return;

  // Detect column-level errors (rate-limit, connection failure, parse).
  // When present, set a clear status label, show a ⚠ badge with the
  // tooltip explaining what went wrong, and replace the Answer area
  // with a styled notice instead of "No structured summary".
  const err = parseColumnError(row);
  if (err) {
    setStatus(tool, err.statusLabel, "warn");
    const wb = role(tool, "warn-badge");
    if (wb) { wb.hidden = false; wb.title = `${err.title}\n\n${err.body}`; }
  } else {
    setStatus(tool, "complete", "complete");
  }

  // Footer
  role(tool, "cost").textContent = `$${(row.usd_cost || 0).toFixed(4)}`;
  const inEst = !!(row.extras && row.extras.input_tokens_estimated);
  const inTok  = row.input_tokens  != null ? row.input_tokens.toLocaleString()  : "—";
  const outTok = row.output_tokens != null ? row.output_tokens.toLocaleString() : "—";
  role(tool, "tokens").textContent = inEst ? `~${inTok} / ${outTok}` : `${inTok} / ${outTok}`;
  role(tool, "model").textContent = formatModelLabel(tool, row);

  // Replace the Answer area with structured cards from the parsed summary,
  // OR a styled error notice for ANY column-level error (rate limit,
  // network error, parse failure, etc.).
  if (err) {
    role(tool, "answer-stream").innerHTML =
      '<div class="rate-limit-note">'
      + '<div class="rl-icon">⚠</div>'
      + `<div class="rl-title">${escapeHtml(err.title)}</div>`
      + `<div class="rl-body">${escapeHtml(err.body)}</div>`
      + '</div>';
  } else {
    populateFinalAnswerCards(tool, row.summary, state[tool].finalText);
  }

  // Verification rows fill in
  role(tool, "verification-body").innerHTML = renderVerification(row.verification);

  // Auto-collapse Background once this tool is done — keeps focus on the answer.
  setBgState(tool, "closed");

  // Once every tool has reached a terminal state (anything except
  // "idle"/"starting"/"running"), pull the full result and render the
  // comparison + math-breakdown sections — even if some tools failed,
  // we still want the math for the ones that succeeded.
  const TERMINAL = new Set(["complete", "failed", "rate limited", "api error", "parse error"]);
  if (TOOLS.every(t => TERMINAL.has(role(t, "status").textContent))) {
    fetch(`/api/run/${activeRunId}/result`).then(r => r.json()).then(renderComparison).catch(() => {});
  }
}

function populateFinalAnswerCards(tool, summary, fallbackText) {
  const stream = role(tool, "answer-stream");
  stream.innerHTML = "";
  summary = summary || {};

  const sections = [
    ["Task summary",  "vulnerabilities_found", summary.vulnerabilities_found],
    ["Code changes",  "fixes_applied",         summary.fixes_applied],
    ["Tests added",   "tests_added",           summary.tests_added],
    ["Test results",  "test_results",          summary.test_results],
  ].filter(([, , body]) => (body || "").trim());

  if (sections.length === 0) {
    // Nothing structured — fall back to the tool's raw final-text if any
    // (e.g., Bob's attempt_completion), otherwise show a friendly note.
    if (fallbackText && fallbackText.trim()) {
      const card = document.createElement("details");
      card.className = "sec-card";
      card.open = true;
      const sum = document.createElement("summary");
      sum.textContent = "Final response";
      const pre = document.createElement("pre");
      pre.textContent = fallbackText.trim();
      card.append(sum, pre);
      stream.appendChild(card);
    } else {
      stream.innerHTML = '<div class="answer-placeholder">No structured summary in response.</div>';
    }
    return;
  }

  for (const [title, key, body] of sections) {
    const card = document.createElement("details");
    card.className = "sec-card";
    // Only "Task summary" expanded by default; click any other header
    // to expand it. Each card scrolls internally.
    card.open = (key === "vulnerabilities_found");
    const sum = document.createElement("summary");
    sum.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = body.trim();
    card.append(sum, pre);
    stream.appendChild(card);
  }
}

function renderVerification(v) {
  if (!v) return "<em>No verification data.</em>";
  const passing = v.tests_failed === 0 && v.tests_total > 0;

  // Semgrep — optional per scenario.
  const semgrepRow = v.semgrep_ran
    ? `<div class="v ${v.semgrep_findings_total === 0 ? "ok" : "fail"}">
         ${v.semgrep_findings_total} (${v.semgrep_findings_high} high)
       </div>`
    : `<div class="v dim">— not run</div>`;

  // Forbidden patterns — optional per scenario. Its own row now (was
  // conflated with "Issue resolved" before, which was misleading for
  // non-vulnerability scenarios).
  let fpRow;
  if (v.forbidden_patterns_configured === false) {
    fpRow = `<div class="v dim">— not configured</div>`;
  } else {
    const clean = v.vuln_pattern_still_present === false;
    fpRow = `<div class="v ${clean ? "ok" : "fail"}">${clean ? "✓ all clear" : "✗ still present"}</div>`;
  }

  // Issue resolved — the bottom-line verdict. Driven by verify.sh's
  // exit code AND, when configured, the absence of any forbidden
  // pattern. verify.sh is the source of truth: its pytest + any
  // task-specific checks are what determine "did the tool actually do
  // the work".
  const fpClean = v.forbidden_patterns_configured === false || v.vuln_pattern_still_present === false;
  const resolved = v.verify_sh_passed === true && fpClean;
  const resolvedRow = `<div class="v ${resolved ? "ok" : "fail"}">${resolved ? "✓ yes" : "✗ no"}</div>`;

  return `<div class="verif-grid">
    <div class="k">Tests</div>
      <div class="v ${passing ? "ok" : "fail"}">${v.tests_passed}/${v.tests_total} passed, ${v.tests_failed} failed</div>
    <div class="k">New tests added</div><div class="v">${v.new_tests_added}</div>
    <div class="k">Semgrep</div>${semgrepRow}
    <div class="k">Forbidden patterns</div>${fpRow}
    <div class="k">Issue resolved</div>${resolvedRow}
    <div class="k">Lines changed</div><div class="v">${v.lines_changed}</div>
    <div class="k">Files modified</div>
      <div class="v">${(v.files_modified || []).slice(0,3).map(escapeHtml).join(", ") || "—"}</div>
  </div>`;
}

// GitHub Copilot's model-multipliers / premium-request page.
const COPILOT_PRICING_URL =
  "https://docs.github.com/en/copilot/managing-copilot/monitoring-usage-and-entitlements/about-premium-requests";

// The underlying provider's official model pricing — used to back up
// the per-token rates we multiply by. Picked from the priced-as model.
function providerPricingUrlFor(modelName) {
  if (!modelName) return null;
  const n = modelName.toLowerCase();
  if (n.startsWith("claude") || n.startsWith("anthropic"))
    return ["Anthropic", "https://docs.anthropic.com/en/docs/about-claude/pricing"];
  if (n.startsWith("gpt") || n.startsWith("o1") || n.startsWith("o3"))
    return ["OpenAI", "https://openai.com/api/pricing/"];
  if (n.startsWith("gemini"))
    return ["Google", "https://ai.google.dev/pricing"];
  if (n.startsWith("grok") || n.startsWith("x.ai"))
    return ["xAI", "https://x.ai/api"];
  return null;
}

function fmtUSD(n)   { return `$${Number(n || 0).toFixed(4)}`; }
function fmtTok(n)   { return Number(n || 0).toLocaleString(); }

// Build one math card per tool. Returns HTML string.
function renderMathCard(row) {
  if (!row || !row.tool) return "";
  const ex = row.extras || {};
  const p  = ex.pricing || {};
  const logoUrl = `/static/logos/${row.tool}.svg`;
  const displayLabel = formatModelLabel(row.tool, row);
  const usd = fmtUSD(row.usd_cost);

  let body = "";

  if (row.tool === "bob") {
    const coins = Number(p.native_value || row.native_cost_value || 0);
    const rate  = Number(p.usd_per_unit || 0);
    body = `
      <div class="math-line"><span class="math-label">Self-reported by Bob</span>
        <span class="math-val">${coins.toFixed(4)} Bobcoins</span></div>
      <div class="math-line"><span class="math-label">Rate</span>
        <span class="math-val">$${rate.toFixed(2)} / Bobcoin
          ${ex.chat_mode ? `· <span class="math-dim">${escapeHtml(ex.chat_mode)} mode</span>` : ""}</span></div>
      <div class="math-eq">
        ${coins.toFixed(4)} × $${rate.toFixed(2)} =
        <strong class="math-total">${usd}</strong>
      </div>
      <div class="math-links">
        <a class="math-link" href="https://bob.ibm.com/pricing" target="_blank" rel="noopener">
          ↗ Bob pricing (FAQ)
        </a>
      </div>`;
  } else if (row.tool === "claude") {
    const mu = ex.model_usage || {};
    const perModel = Object.entries(mu).map(([m, v]) => {
      const c = Number(v && v.costUSD || 0);
      return c > 0
        ? `<div class="math-sub">${escapeHtml(m)} · ${fmtUSD(c)}</div>`
        : "";
    }).join("");
    // Pick the dominant model (highest cost) for the rates link label
    const dominant = Object.entries(mu)
      .sort((a, b) => Number(b[1].costUSD || 0) - Number(a[1].costUSD || 0))[0];
    const dominantName = dominant ? dominant[0] : (row.model || "");
    body = `
      <div class="math-line"><span class="math-label">Self-reported by Claude</span>
        <span class="math-val">${fmtUSD(row.usd_cost)} USD (sum of all internal model usage)</span></div>
      ${perModel ? `<div class="math-breakdown-sub"><div class="math-dim">Breakdown:</div>${perModel}</div>` : ""}
      <div class="math-eq">
        Total = <strong class="math-total">${usd}</strong>
      </div>
      <div class="math-links">
        <a class="math-link" href="https://docs.anthropic.com/en/docs/about-claude/pricing" target="_blank" rel="noopener">
          ↗ Anthropic ${escapeHtml(prettifyModel(dominantName))} rates
        </a>
      </div>`;
  } else if (row.tool === "copilot") {
    const rb = p.rate_breakdown || {};
    const inT  = Number(rb.input_tokens   || row.input_tokens   || 0);
    const outT = Number(rb.output_tokens  || row.output_tokens  || 0);
    const caT  = Number(rb.cached_tokens  || row.cached_tokens  || 0);
    const inR  = Number(rb.input_per_mtok  || 0);
    const outR = Number(rb.output_per_mtok || 0);
    const caR  = Number(rb.cached_per_mtok || 0);
    const inC  = inT  / 1_000_000 * inR;
    const outC = outT / 1_000_000 * outR;
    const caC  = caT  / 1_000_000 * caR;
    const inEst = !!ex.input_tokens_estimated;

    const pricedAs = p.priced_as_model || row.model;
    const provider = providerPricingUrlFor(pricedAs);
    const premReq = (ex.premium_requests != null) ? ex.premium_requests : "—";
    body = `
      <div class="math-line"><span class="math-label">Self-reported by Copilot</span>
        <span class="math-val">${premReq} premium req · ${fmtTok(outT)} output tok</span></div>
      <div class="math-line"><span class="math-label">Input</span>
        <span class="math-val">${fmtTok(inT)} tok × $${inR.toFixed(2)} / 1M = ${fmtUSD(inC)}</span></div>
      <div class="math-line"><span class="math-label">Output</span>
        <span class="math-val">${fmtTok(outT)} tok × $${outR.toFixed(2)} / 1M = ${fmtUSD(outC)}</span></div>
      <div class="math-line"><span class="math-label">Cached</span>
        <span class="math-val">${fmtTok(caT)} tok × $${caR.toFixed(2)} / 1M = ${fmtUSD(caC)}</span></div>
      <div class="math-eq">
        Total = <strong class="math-total">${usd}</strong>
      </div>
      <div class="math-links">
        <a class="math-link" href="${COPILOT_PRICING_URL}" target="_blank" rel="noopener">
          ↗ Copilot multipliers
        </a>
        ${provider ? `<a class="math-link" href="${escapeHtml(provider[1])}" target="_blank" rel="noopener">
          ↗ ${escapeHtml(provider[0])} ${escapeHtml(prettifyModel(pricedAs))} rates
        </a>` : ""}
      </div>`;
  }

  return `
    <div class="math-card" data-tool="${row.tool}">
      <header class="math-head">
        <img class="tool-logo" src="${logoUrl}" alt="${row.tool}" />
        <span class="math-tool">${escapeHtml(displayLabel)}</span>
        <span class="math-cost">${usd}</span>
      </header>
      <div class="math-body">${body}</div>
    </div>`;
}

function renderMathBreakdown(result) {
  const tools = (result && result.tools) || [];
  if (!tools.length) return;
  $("#math-breakdown").hidden = false;
  $("#math-body").innerHTML = tools.map(renderMathCard).join("");
}

// Parse + render kept in /static/diff_render.js so report.html can reuse.
// These functions are left here as a safe fallback in case the shared
// script failed to load.
function parseUnifiedDiff(text) {
  const lines = text.split("\n");
  const files = [];
  let curFile = null;
  let curHunk = null;
  let oldLn = 0, newLn = 0;

  function startHunk(header) {
    // @@ -oldStart,oldCount +newStart,newCount @@ optional-context
    const m = header.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
    if (!m) return null;
    oldLn = parseInt(m[1], 10);
    newLn = parseInt(m[2], 10);
    return { header, context: m[3].trim(), rows: [] };
  }

  for (const raw of lines) {
    if (raw.startsWith("diff --git") || raw.startsWith("diff ")) {
      if (curFile) {
        if (curHunk) curFile.hunks.push(curHunk);
        files.push(curFile);
      }
      curFile = { path: null, hunks: [], added: 0, removed: 0 };
      curHunk = null;
      continue;
    }
    if (!curFile) {
      // Lines outside any file block (rare with --no-index output); skip.
      continue;
    }
    if (raw.startsWith("+++ ")) {
      // +++ b/path/to/file  (or +++ b)
      curFile.path = raw.slice(4).replace(/^b\//, "").replace(/^b$/, "(new file)").trim();
      continue;
    }
    if (raw.startsWith("--- ")) {
      // We prefer the +++ path but fall back to --- if +++ is missing/empty.
      if (!curFile.path) curFile.path = raw.slice(4).replace(/^a\//, "").trim();
      continue;
    }
    if (raw.startsWith("index ") || raw.startsWith("new file") ||
        raw.startsWith("deleted file") || raw.startsWith("similarity") ||
        raw.startsWith("rename")) {
      continue;
    }
    if (raw.startsWith("@@")) {
      if (curHunk) curFile.hunks.push(curHunk);
      curHunk = startHunk(raw);
      continue;
    }
    if (!curHunk) continue;
    if (raw.startsWith("+")) {
      curHunk.rows.push({ kind: "add", oldLn: null, newLn, text: raw.slice(1) });
      newLn++; curFile.added++;
    } else if (raw.startsWith("-")) {
      curHunk.rows.push({ kind: "del", oldLn, newLn: null, text: raw.slice(1) });
      oldLn++; curFile.removed++;
    } else if (raw.startsWith("\\")) {
      // "\ No newline at end of file" — annotation, not a code line
      curHunk.rows.push({ kind: "info", oldLn: null, newLn: null, text: raw });
    } else {
      // context line (starts with " " or empty)
      const t = raw.startsWith(" ") ? raw.slice(1) : raw;
      curHunk.rows.push({ kind: "ctx", oldLn, newLn, text: t });
      oldLn++; newLn++;
    }
  }
  if (curFile) {
    if (curHunk) curFile.hunks.push(curHunk);
    files.push(curFile);
  }
  return files;
}

function renderDiffPre(diffText) {
  if (window.DiffRender) return window.DiffRender.render(diffText);
  if (!diffText) {
    return `<div class="diff-empty">No changes detected.</div>`;
  }
  const files = parseUnifiedDiff(diffText);
  if (!files.length) {
    return `<pre class="diff-pre">${escapeHtml(diffText)}</pre>`;
  }
  return `<div class="diff-pre">${files.map(renderDiffFile).join("")}</div>`;
}

function renderDiffFile(file) {
  const path = file.path || "(unknown file)";
  const stats = `<span class="diff-stat-add">+${file.added}</span> <span class="diff-stat-del">−${file.removed}</span>`;
  const hunks = file.hunks.map(renderDiffHunk).join("");
  return `<div class="diff-file-block">
    <div class="diff-file-bar">
      <span class="diff-file-path">${escapeHtml(path)}</span>
      <span class="diff-file-stats">${stats}</span>
    </div>
    ${hunks}
  </div>`;
}

function renderDiffHunk(hunk) {
  const ctx = hunk.context ? ` <span class="diff-hunk-ctx">${escapeHtml(hunk.context)}</span>` : "";
  const rowsHtml = hunk.rows.map(r => {
    const oldN = r.oldLn != null ? r.oldLn : "";
    const newN = r.newLn != null ? r.newLn : "";
    const marker = r.kind === "add" ? "+" : r.kind === "del" ? "−" : r.kind === "info" ? "" : " ";
    return `<div class="diff-row diff-${r.kind}">
      <span class="diff-gutter diff-gutter-old">${oldN}</span>
      <span class="diff-gutter diff-gutter-new">${newN}</span>
      <span class="diff-marker">${marker}</span>
      <span class="diff-content">${escapeHtml(r.text) || "&nbsp;"}</span>
    </div>`;
  }).join("");
  return `<div class="diff-hunk-block">
    <div class="diff-hunk-bar">@@ ${escapeHtml(hunk.header.replace(/^@@\s*/, "").replace(/\s*@@.*$/, ""))} @@${ctx}</div>
    ${rowsHtml}
  </div>`;
}

function renderDiffCard(row) {
  const logoUrl = `/static/logos/${row.tool}.svg`;
  const displayLabel = (row.tool || "").charAt(0).toUpperCase() + (row.tool || "").slice(1);
  const verif = row.verification || {};
  const files = (verif.files_modified || []);
  const lines = verif.lines_changed != null ? verif.lines_changed : "—";
  const diffText = verif.diff_text || "";
  const fileBadge = files.length
    ? `${files.length} file${files.length === 1 ? "" : "s"} · ${lines} line${lines === 1 ? "" : "s"}`
    : "no changes";
  return `
    <details class="math-card diff-card" data-tool="${row.tool}">
      <summary class="math-head">
        <img class="tool-logo" src="${logoUrl}" alt="${row.tool}" />
        <span class="math-tool">${escapeHtml(displayLabel)}</span>
        <span class="diff-badge">${escapeHtml(fileBadge)}</span>
        <span class="diff-chev">▾</span>
      </summary>
      <div class="math-body">${renderDiffPre(diffText)}</div>
    </details>`;
}

function renderDiffBreakdown(result) {
  const tools = (result && result.tools) || [];
  if (!tools.length) return;
  const anyDiff = tools.some(t => (t.verification && t.verification.diff_text));
  if (!anyDiff) return;
  $("#diff-breakdown").hidden = false;
  $("#diff-body").innerHTML = tools.map(renderDiffCard).join("");
}

function renderComparison(result) {
  $("#comparison").hidden = false;
  renderMathBreakdown(result);
  renderDiffBreakdown(result);
  const tools = (result && result.tools) || [];
  if (!tools.length) return;
  const winnerCost = [...tools].sort((a, b) => (a.usd_cost || 0) - (b.usd_cost || 0))[0]?.tool;
  const winnerTime = [...tools].sort((a, b) => (a.wall_clock_ms || 0) - (b.wall_clock_ms || 0))[0]?.tool;

  const rows = [
    ["Wall clock",  r => `${(r.wall_clock_ms / 1000).toFixed(1)}s`],
    ["USD cost",    r => `$${(r.usd_cost || 0).toFixed(4)}`],
    ["Model",       r => formatModelLabel(r.tool, r)],
    ["Input tok.",  r => r.input_tokens  != null ? r.input_tokens.toLocaleString()  : "—"],
    ["Output tok.", r => r.output_tokens != null ? r.output_tokens.toLocaleString() : "—"],
    ["Tests pass",  r => (r.verification ? `${r.verification.tests_passed}/${r.verification.tests_total}` : "—")],
    ["Tests fail",  r => (r.verification ? r.verification.tests_failed : "—")],
    ["New tests",   r => (r.verification ? r.verification.new_tests_added : "—")],
    ["Semgrep",     r => (r.verification ? r.verification.semgrep_findings_total : "—")],
    ["Issue resolved", r => (r.verification && r.verification.vuln_pattern_still_present === false ? "✓" : "✗")],
    ["Lines",       r => (r.verification ? r.verification.lines_changed : "—")],
  ];

  let html = `<table class="cmp-table"><thead><tr><th>Metric</th>`;
  for (const t of tools) html += `<th>${escapeHtml(t.tool)}</th>`;
  html += `</tr></thead><tbody>`;
  for (const [label, fn] of rows) {
    html += `<tr><td>${label}</td>`;
    for (const t of tools) {
      const v = fn(t);
      const winner =
        (label === "USD cost"   && t.tool === winnerCost) ||
        (label === "Wall clock" && t.tool === winnerTime);
      html += `<td class="num ${winner ? "winner" : ""}">${escapeHtml(String(v))}</td>`;
    }
    html += `</tr>`;
  }
  html += `</tbody></table>`;
  $("#comparison-body").innerHTML = html;
}

// ─────────────── Helpers ───────────────

function pickToolIcon(name) {
  if (!name) return "•";
  const n = name.toLowerCase();
  if (n.includes("bash") || n.includes("exec") || n.includes("command")) return "▶";
  if (n.includes("read") || n.includes("view") || n.includes("cat"))     return "📄";
  if (n.includes("edit") || n.includes("write") || n.includes("update")) return "✎";
  if (n.includes("grep") || n.includes("search") || n.includes("find"))  return "🔍";
  if (n.includes("test") || n.includes("pytest"))                        return "🧪";
  if (n.includes("todo"))                                                 return "✓";
  if (n.includes("attempt_completion") || n.includes("report"))           return "★";
  return "•";
}

function oneLineArgPreview(name, args) {
  if (args == null) return "";
  if (typeof args === "string") return truncate(args, 100);
  if (typeof args !== "object") return String(args);
  const priority = ["command", "path", "file_path", "filePath", "pattern",
                    "query", "intent", "content", "old_string", "new_string"];
  for (const k of priority) {
    if (args[k]) {
      const v = typeof args[k] === "string" ? args[k] : prettyJson(args[k]);
      return truncate(v.replace(/\s+/g, " "), 100);
    }
  }
  return truncate(prettyJson(args).replace(/\s+/g, " "), 100);
}

function prettyJson(x) {
  try { return JSON.stringify(x, null, 2); } catch { return String(x); }
}
function truncate(s, n) {
  s = String(s || "");
  return s.length <= n ? s : s.slice(0, n) + `\n… [truncated ${s.length - n} chars]`;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

function prettifyModel(name) {
  if (!name) return "—";
  let s = name;
  s = s.replace(/^claude-/i, "").replace(/^anthropic\./i, "");
  s = s.replace(/-(\d+)-(\d+)$/, "-$1.$2");
  const m = s.match(/^([a-z0-9]+)-(.+)$/i);
  if (m) {
    const fam = m[1].toUpperCase() === m[1] ? m[1] : m[1][0].toUpperCase() + m[1].slice(1);
    return `${fam} ${m[2]}`;
  }
  return s;
}

function formatModelLabel(tool, row) {
  const ex = row.extras || {};
  // Bob: always recompute. Older runs persisted "Advanced mode" — we
  // moved to just "Advanced" and don't want stale labels showing up.
  if (tool === "bob") {
    const mode = ex.chat_mode || "advanced";
    return mode[0].toUpperCase() + mode.slice(1);
  }
  if (ex.display_model) return ex.display_model;
  if (tool === "copilot") {
    const proj = ex.pricing && ex.pricing.is_projection ? ex.pricing.priced_as_model : null;
    return prettifyModel(proj || row.model);
  }
  return prettifyModel(row.model);
}

// ─────────────── Run lifecycle ───────────────

async function startRun() {
  const scenarioId = $("#scenario-picker").value;
  const btn = $("#run-btn");
  btn.disabled = true;
  $("#status-pill").className = "pill running";
  $("#status-pill").textContent = "Running";
  $("#comparison").hidden = true;
  const mb = $("#math-breakdown");
  if (mb) mb.hidden = true;

  TOOLS.forEach(resetCol);
  TOOLS.forEach(t => setStatus(t, "starting", "running"));

  let resp;
  try {
    resp = await fetch("/api/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId }),
    });
  } catch {
    $("#status-pill").className = "pill failed";
    $("#status-pill").textContent = "Failed to start";
    btn.disabled = false;
    return;
  }
  if (!resp.ok) {
    $("#status-pill").className = "pill failed";
    $("#status-pill").textContent = "Failed to start";
    btn.disabled = false;
    return;
  }
  const meta = await resp.json();
  activeRunId = meta.run_id;
  activeDisplayOverrides = meta.display_overrides || {};

  TOOLS.forEach(t => {
    setStatus(t, "running", "running");
    startTimer(t);
    const es = new EventSource(`/api/stream/${meta.run_id}/${t}`);
    es.addEventListener("stdout", (e) => {
      const evt = normalize(t, e.data);
      if (evt) render(t, evt);
    });
    es.addEventListener("done", (e) => {
      onDone(t, e.data);
      es.close();
    });
    es.onerror = () => {
      setStatus(t, "failed", "failed");
      stopTimer(t);
    };
  });

  const poll = setInterval(async () => {
    let s;
    try { s = await fetch(`/api/run/${meta.run_id}/status`).then(r => r.json()); } catch { return; }
    if (!s) return;
    if (s.status === "complete") {
      $("#status-pill").className = "pill complete";
      $("#status-pill").textContent = "Complete";
      btn.disabled = false;
      clearInterval(poll);
    } else if (s.status === "failed") {
      $("#status-pill").className = "pill failed";
      $("#status-pill").textContent = "Failed";
      btn.disabled = false;
      clearInterval(poll);
    }
  }, 1500);
}

async function deleteRun(run_id) {
  if (!confirm(`Delete run ${run_id.slice(0,24)}? This removes its DB rows AND the runs/${run_id}/ folder.`)) return;
  const resp = await fetch(`/api/runs/${encodeURIComponent(run_id)}`, { method: "DELETE" });
  if (!resp.ok) { alert("Failed to delete run"); return; }
  loadHistory();
}

async function deleteAllRuns() {
  if (!confirm("Delete ALL past runs?\nThis wipes runs.db and removes every runs/<id>/ folder. Cannot be undone.")) return;
  const resp = await fetch("/api/runs", { method: "DELETE" });
  if (!resp.ok) { alert("Failed to delete runs"); return; }
  loadHistory();
}

async function loadHistory() {
  const rows = await fetch("/api/runs").then(r => r.json()).catch(() => []);
  $("#history").hidden = false;
  // Smooth-scroll the section into view
  setTimeout(() => $("#history").scrollIntoView({ behavior: "smooth", block: "start" }), 50);

  if (!rows.length) {
    $("#history-body").innerHTML = '<div class="hint">No past runs yet.</div>';
    return;
  }

  // Group rows by run_id so each run is ONE table row with all three
  // tools side-by-side (the per-tool rows in /api/runs are how SQLite
  // stores them, but the user reads runs as a unit).
  const byRun = {};
  for (const r of rows) {
    if (!byRun[r.run_id]) {
      byRun[r.run_id] = {
        run_id: r.run_id,
        scenario_id: r.scenario_id,
        started_at: r.started_at,
        tools: {},
        total_usd: 0,
      };
    }
    byRun[r.run_id].tools[r.tool] = r;
    byRun[r.run_id].total_usd += Number(r.usd_cost || 0);
  }
  const runs = Object.values(byRun).sort((a, b) =>
    String(b.started_at || "").localeCompare(String(a.started_at || ""))
  );

  // Per-run colouring rule:
  //   cheapest successful tool   → green ✓
  //   other successful tools     → yellow ✓
  //   any failed / errored tool  → red ⚠
  // A tool is "successful" iff exit_code === 0 AND no error string.
  const isSuccessful = (t) => t && t.exit_code === 0 && !(t.error || "").trim();

  const cheapestToolName = (run) => {
    let bestName = null, bestCost = Infinity;
    for (const [name, t] of Object.entries(run.tools)) {
      if (!isSuccessful(t)) continue;
      const c = Number(t.usd_cost || 0);
      if (c < bestCost) { bestCost = c; bestName = name; }
    }
    return bestName;
  };

  const toolCell = (toolName, t, cheapest) => {
    if (!t) return '<div class="tool-cell empty">—</div>';
    let cls, icon;
    if (!isSuccessful(t)) {
      cls = "fail"; icon = "⚠";
    } else if (toolName === cheapest) {
      cls = "winner"; icon = "✓";
    } else {
      cls = "runner-up"; icon = "✓";
    }
    const tip = t.error ? t.error : "";
    return `<div class="tool-cell ${cls}" title="${escapeHtml(tip)}">
      <span class="tc-icon">${icon}</span>
      <span class="tc-cost">$${Number(t.usd_cost || 0).toFixed(4)}</span>
    </div>`;
  };

  let html = `<div class="runs-toolbar">
    <span class="runs-count">${runs.length} run${runs.length === 1 ? "" : "s"}</span>
    <button class="danger-btn" onclick="deleteAllRuns()">🗑 Delete all</button>
  </div>
  <table class="cmp-table runs-table">
    <thead>
      <tr>
        <th>Scenario</th>
        <th>Started</th>
        <th>Bob</th>
        <th>Claude</th>
        <th>Copilot</th>
        <th class="action-col">Open</th>
        <th class="action-col">Delete</th>
      </tr>
    </thead>
    <tbody>`;
  for (const r of runs) {
    const started = (r.started_at || "").replace("T", " ").slice(0, 19);
    const cheapest = cheapestToolName(r);
    html += `<tr>
      <td>${escapeHtml(r.scenario_id || "")}</td>
      <td class="started">${escapeHtml(started)}</td>
      <td>${toolCell("bob", r.tools.bob, cheapest)}</td>
      <td>${toolCell("claude", r.tools.claude, cheapest)}</td>
      <td>${toolCell("copilot", r.tools.copilot, cheapest)}</td>
      <td class="action-col">
        <a class="details-link" href="/run/${escapeHtml(r.run_id)}" title="Open run report">↗</a>
      </td>
      <td class="action-col">
        <button class="icon-btn" title="Delete this run"
                onclick="deleteRun('${escapeHtml(r.run_id)}')">🗑</button>
      </td>
    </tr>`;
  }
  html += `</tbody></table>`;
  $("#history-body").innerHTML = html;
}

function updateScenarioDescription() {
  const sel = $("#scenario-picker");
  const info = $("#scenario-info");
  if (!sel || !info) return;
  const opt = sel.options[sel.selectedIndex];
  if (!opt) { info.hidden = true; return; }
  const title  = opt.getAttribute("data-title") || opt.textContent || "";
  const desc   = opt.getAttribute("data-description") || "";
  const prompt = opt.getAttribute("data-prompt") || "";
  const type   = opt.getAttribute("data-type") || "";
  const verif  = opt.getAttribute("data-verifications") || "";

  $("#scenario-title").textContent = title.trim();
  $("#scenario-description").textContent = desc.trim();
  $("#scenario-prompt").textContent = prompt;

  const typeEl = info.querySelector('[data-role="scenario-type"]');
  if (typeEl) {
    typeEl.textContent = type;
    typeEl.hidden = !type;
  }
  const verifEl = info.querySelector('[data-role="scenario-verifications"]');
  if (verifEl) verifEl.textContent = verif;
  info.hidden = false;
}

document.addEventListener("DOMContentLoaded", () => {
  TOOLS.forEach(resetCol);
  TOOLS.forEach(t => {
    const btn = role(t, "bg-toggle");
    if (btn) btn.addEventListener("click", () => toggleBgState(t));
  });
  $("#run-btn").addEventListener("click", startRun);
  const hb = $("#history-btn");
  if (hb) hb.addEventListener("click", loadHistory);

  // Scenario description: render on load + update on change
  const picker = $("#scenario-picker");
  if (picker) picker.addEventListener("change", updateScenarioDescription);
  updateScenarioDescription();
});
