import { fmtDateTime } from "../lib/format";
import type { AuditEntry } from "../types";

export default function AuditLogTable({ logs }: { logs: AuditEntry[] }) {
  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>When</th>
            <th>Action type</th>
            <th>Milestone</th>
            <th>Field</th>
            <th>Old</th>
            <th>New</th>
            <th>Reason</th>
            <th>Actor</th>
            <th>Mode</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {logs.length === 0 && (
            <tr><td colSpan={10} className="center muted" style={{ padding: 26 }}>
              No changes in the audit journal. Records are appended here whenever the overlay is written.
            </td></tr>
          )}
          {logs.map((l) => (
            <tr key={l.id}>
              <td className="date">{fmtDateTime(l.created_at)}</td>
              <td><span className="badge badge-mono">{l.action_type}</span></td>
              <td className="cell-code">{l.milestone_code}</td>
              <td style={{ fontSize: 12 }}>{l.field || "—"}</td>
              <td className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>{l.old_value || "—"}</td>
              <td className="mono" style={{ fontSize: 11, color: "var(--success)" }}>{l.new_value || "—"}</td>
              <td style={{ fontSize: 11, color: "var(--text-muted)" }}>{l.reason || "—"}</td>
              <td style={{ fontSize: 12 }}>{l.actor || "—"}</td>
              <td><span className="badge">{l.mode}</span></td>
              <td style={{ fontSize: 12 }}>{l.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
