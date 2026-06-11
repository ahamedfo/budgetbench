"use client";
import { useState } from "react";
import { api } from "../lib/api";
import { usd, usd0, int, secs, TOOL_LABEL, TOOL_COLOR } from "../lib/format";

export default function DeptDrilldown({ proj, selectedLabel }) {
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState({}); // id -> detail

  if (!proj) return null;

  const toggle = (id) => {
    if (openId === id) return setOpenId(null);
    setOpenId(id);
    if (!detail[id]) {
      api.departmentDetail(id).then((d) => setDetail((m) => ({ ...m, [id]: d }))).catch(() => {});
    }
  };

  return (
    <section>
      <h2 className="text-base font-semibold mb-1">Department Drill-down</h2>
      <p className="text-sm text-carbon-subtle mb-3">Click a department to see its measured per-agent cost and the mix of work it runs.</p>
      <div className="panel overflow-hidden">
        {proj.departments.map((d) => {
          const open = openId === d.department_id;
          const det = detail[d.department_id];
          return (
            <div key={d.department_id} className="border-b border-carbon-border last:border-b-0">
              <button
                onClick={() => toggle(d.department_id)}
                className="w-full grid grid-cols-[1.4fr_1fr_1fr_0.5fr] items-center px-5 py-3.5 text-left hover:bg-carbon-bg/50 transition-colors"
              >
                <div className="font-medium">{d.department}</div>
                <div className="text-sm text-carbon-subtle">{int(d.volume)} tasks/mo</div>
                <div className="metric-num text-sm text-right">
                  {usd0(d.projected_usd)}<span className="text-carbon-subtle"> /mo on {selectedLabel}</span>
                </div>
                <div className="text-right text-carbon-subtle">{open ? "▴" : "▾"}</div>
              </button>

              {open && (
                <div className="px-5 pb-5 pt-1 bg-carbon-bg/30">
                  {!det ? (
                    <div className="text-sm text-carbon-subtle py-2">Loading…</div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                      <div>
                        <div className="text-[11px] uppercase tracking-wide text-carbon-subtle mb-2">Measured cost per task (by agent)</div>
                        <div className="space-y-1.5">
                          {(det.by_tool || []).map((t) => (
                            <div key={t.tool} className="flex items-center gap-2 text-sm">
                              <span className="w-2 h-2 rounded-full" style={{ background: TOOL_COLOR[t.tool] }} />
                              <span className="w-20">{TOOL_LABEL[t.tool] || t.tool}</span>
                              <span className="metric-num font-medium">{usd(t.usd / Math.max(t.tasks, 1))}</span>
                              <span className="text-carbon-subtle text-xs">· {secs(t.avg_duration_ms)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-wide text-carbon-subtle mb-2">Work mix (by task type)</div>
                        <div className="space-y-1.5">
                          {(det.by_task_type || []).map((tt) => (
                            <div key={tt.task_type} className="flex items-center justify-between text-sm">
                              <span>{tt.task_type}</span>
                              <span className="text-carbon-subtle text-xs">{tt.tasks} run{tt.tasks > 1 ? "s" : ""}</span>
                            </div>
                          ))}
                          {(det.by_task_type || []).length === 0 && (
                            <div className="text-sm text-carbon-subtle">No runs yet.</div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
