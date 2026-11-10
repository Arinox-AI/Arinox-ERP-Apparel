import { useMemo } from "react";
import { fmtDate } from "../lib/format";
import { statusTone, toneColor } from "../lib/status";
import StatusPill from "../components/StatusPill";
import type { TnaMilestone } from "../types";

const COLUMNS: { key: string; label: string; match: (s: string) => boolean }[] = [
  { key: "notstarted", label: "Not started", match: (s) => s === "Not started" || s === "Not recorded" },
  { key: "inprogress", label: "In progress", match: (s) => s === "In progress" },
  { key: "waiting", label: "Waiting", match: (s) => s.startsWith("Waiting") },
  { key: "atrisk", label: "At risk / Blocked", match: (s) => s === "At risk" || s === "Blocked" },
  { key: "late", label: "Late", match: (s) => s === "Overdue" || s === "Completed late" },
  { key: "done", label: "Done", match: (s) => s === "Completed" },
];

/** BoardView — the plan as a kanban of milestone statuses. Read/filter lens. */
export default function BoardView({
  milestones, onSelect,
}: {
  milestones: TnaMilestone[];
  onSelect: (code: string) => void;
}) {
  const cols = useMemo(
    () => COLUMNS.map((c) => ({ ...c, rows: milestones.filter((m) => c.match(m.status)) })),
    [milestones]
  );

  return (
    <div className="board">
      {cols.map((c) => (
        <div key={c.key} className="board-col">
          <div className="board-col-head">
            <span className="board-col-dot" style={{ background: toneColor(statusTone(c.rows[0]?.status || "Not started")) }} />
            <span className="board-col-name">{c.label}</span>
            <span className="pill-count">{c.rows.length}</span>
          </div>
          <div className="board-col-body">
            {c.rows.length === 0 && <div className="board-empty muted">—</div>}
            {c.rows.map((m) => (
              <button key={m.code} className="board-card" onClick={() => onSelect(m.code)}
                style={{ borderLeftColor: toneColor(statusTone(m.status)) }}>
                <span className="board-card-name">{m.name}</span>
                <span className="board-card-code mono">{m.code}</span>
                <span className="board-card-foot">
                  <span className="muted">{m.owner_role || m.owner || "—"}</span>
                  <span className="mono">{fmtDate(m.planned_finish)}</span>
                </span>
                {m.is_critical && <span className="board-card-cp" title="On the critical path">◆ critical</span>}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
