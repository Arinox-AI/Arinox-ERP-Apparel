import { Play, Undo2 } from "lucide-react";
import { fmtDateTime } from "../lib/format";
import type { ActionRecord } from "../types";

function StatusChip({ status }: { status: string }) {
  const cls = status === "applied" ? "badge badge-success" : status === "staged" ? "badge badge-warning" : "badge";
  return <span className={cls}>{status}</span>;
}

export default function ActionHistoryTable({
  actions, onRun, onRollback, busyId,
}: {
  actions: ActionRecord[];
  onRun: (action: ActionRecord) => void;
  onRollback: (action: ActionRecord) => void;
  busyId?: string | null;
}) {
  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>Action</th>
            <th>Milestone</th>
            <th>Kind</th>
            <th>Changes</th>
            <th>Status</th>
            <th>Actor</th>
            <th>Created</th>
            <th>Applied</th>
            <th className="right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {actions.length === 0 && (
            <tr><td colSpan={9} className="center muted" style={{ padding: 26 }}>No write actions recorded yet.</td></tr>
          )}
          {actions.map((a) => (
            <tr key={a.action_id}>
              <td className="mono" style={{ fontSize: 11 }}>{a.action_id.slice(0, 8)}</td>
              <td className="cell-code">{a.milestone_code}</td>
              <td style={{ fontSize: 12 }}>{a.kind}</td>
              <td style={{ fontSize: 11, color: "var(--text-muted)" }}>
                {a.changes.length === 0 ? "—" : a.changes.map((c) => `${c.field}: ${c.old}→${c.new}`).join("; ")}
              </td>
              <td><StatusChip status={a.status} /></td>
              <td style={{ fontSize: 12 }}>{a.actor || "—"}</td>
              <td className="date">{fmtDateTime(a.created_at)}</td>
              <td className="date">{fmtDateTime(a.applied_at)}</td>
              <td className="right">
                {a.status === "staged" && (
                  <button className="btn btn-primary btn-sm" disabled={busyId === a.action_id} onClick={() => onRun(a)}>
                    <Play size={12} /> Run
                  </button>
                )}
                {a.status === "applied" && (
                  <button className="btn btn-secondary btn-sm" disabled={busyId === a.action_id} onClick={() => onRollback(a)}>
                    <Undo2 size={12} /> Rollback
                  </button>
                )}
                {a.status === "rolled_back" && <span className="muted" style={{ fontSize: 12 }}>rolled back</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
