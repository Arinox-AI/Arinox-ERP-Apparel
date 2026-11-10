import type { OwnersBlock } from "../types";

/**
 * Owner workload — who is carrying how much, and how exposed they are.
 * Read-only; the write path lives in the milestone drawer.
 */
export default function OwnerWorkloadTable({ block }: { block: OwnersBlock }) {
  const rows = block?.owners || [];
  if (!rows.length) {
    return <div className="empty"><div className="empty-title">No owners</div><div>No milestone ownership could be derived.</div></div>;
  }
  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>Owner</th>
            <th>Role</th>
            <th className="right">Milestones</th>
            <th className="right">Done</th>
            <th className="right">Open</th>
            <th className="right">Overdue</th>
            <th className="right">Critical</th>
            <th className="right">Progress</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.owner}>
              <td style={{ fontWeight: 500 }}>{o.owner}</td>
              <td style={{ fontSize: 12 }} className="muted">{o.role || "—"}</td>
              <td className="right mono">{o.total}</td>
              <td className="right mono" style={{ color: "var(--success)" }}>{o.completed}</td>
              <td className="right mono">{o.open}</td>
              <td className="right mono" style={{ color: o.overdue ? "var(--error)" : undefined }}>{o.overdue}</td>
              <td className="right mono">{o.critical}</td>
              <td className="right">
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
                  <span style={{ width: 56, height: 6, background: "var(--surface-accent)", borderRadius: 3, overflow: "hidden", display: "inline-block" }}>
                    <span style={{ display: "block", height: "100%", width: `${Math.min(100, o.progress_pct)}%`, background: "var(--accent-teal)" }} />
                  </span>
                  <span className="mono muted" style={{ fontSize: 11 }}>{Math.round(o.progress_pct)}%</span>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
