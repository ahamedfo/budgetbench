/* Shared unified-diff renderer used by both the live UI (app.js) and the
   past-run report page. Exposes window.DiffRender = { render(diffText) }.
   Renders GitHub-style: file banner, hunk banner, rows with old/new line
   gutters and full-width +/− backgrounds. */
(function () {
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  function parseUnifiedDiff(text) {
    const lines = text.split("\n");
    const files = [];
    let curFile = null, curHunk = null, oldLn = 0, newLn = 0;

    function startHunk(header) {
      const m = header.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
      if (!m) return null;
      oldLn = parseInt(m[1], 10);
      newLn = parseInt(m[2], 10);
      return { header, context: m[3].trim(), rows: [] };
    }

    for (const raw of lines) {
      if (raw.startsWith("diff --git") || raw.startsWith("diff ")) {
        if (curFile) { if (curHunk) curFile.hunks.push(curHunk); files.push(curFile); }
        curFile = { path: null, hunks: [], added: 0, removed: 0 };
        curHunk = null;
        continue;
      }
      if (!curFile) continue;
      if (raw.startsWith("+++ ")) {
        curFile.path = raw.slice(4).replace(/^b\//, "").replace(/^b$/, "(new file)").trim();
        continue;
      }
      if (raw.startsWith("--- ")) {
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
        curHunk.rows.push({ kind: "info", oldLn: null, newLn: null, text: raw });
      } else {
        const t = raw.startsWith(" ") ? raw.slice(1) : raw;
        curHunk.rows.push({ kind: "ctx", oldLn, newLn, text: t });
        oldLn++; newLn++;
      }
    }
    if (curFile) { if (curHunk) curFile.hunks.push(curHunk); files.push(curFile); }
    return files;
  }

  function renderFile(file) {
    const path = file.path || "(unknown file)";
    const stats = `<span class="diff-stat-add">+${file.added}</span> <span class="diff-stat-del">−${file.removed}</span>`;
    const hunks = file.hunks.map(renderHunk).join("");
    return `<div class="diff-file-block">
      <div class="diff-file-bar">
        <span class="diff-file-path">${esc(path)}</span>
        <span class="diff-file-stats">${stats}</span>
      </div>${hunks}</div>`;
  }

  function renderHunk(hunk) {
    const ctx = hunk.context ? ` <span class="diff-hunk-ctx">${esc(hunk.context)}</span>` : "";
    const range = esc(hunk.header.replace(/^@@\s*/, "").replace(/\s*@@.*$/, ""));
    const rows = hunk.rows.map(r => {
      const oldN = r.oldLn != null ? r.oldLn : "";
      const newN = r.newLn != null ? r.newLn : "";
      const marker = r.kind === "add" ? "+" : r.kind === "del" ? "−" : r.kind === "info" ? "" : " ";
      return `<div class="diff-row diff-${r.kind}">
        <span class="diff-gutter diff-gutter-old">${oldN}</span>
        <span class="diff-gutter diff-gutter-new">${newN}</span>
        <span class="diff-marker">${marker}</span>
        <span class="diff-content">${esc(r.text) || "&nbsp;"}</span>
      </div>`;
    }).join("");
    return `<div class="diff-hunk-block">
      <div class="diff-hunk-bar">@@ ${range} @@${ctx}</div>${rows}</div>`;
  }

  function render(diffText) {
    if (!diffText) return `<div class="diff-empty">No changes detected.</div>`;
    const files = parseUnifiedDiff(diffText);
    if (!files.length) return `<pre class="diff-pre">${esc(diffText)}</pre>`;
    return `<div class="diff-pre">${files.map(renderFile).join("")}</div>`;
  }

  window.DiffRender = { render, parse: parseUnifiedDiff };
})();
