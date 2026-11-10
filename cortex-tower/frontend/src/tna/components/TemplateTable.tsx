import { fmtWdays, DASH } from "../lib/format";
import type { TnaTemplateMilestone } from "../types";

export default function TemplateTable({ milestones }: { milestones: TnaTemplateMilestone[] }) {
  return (
    <div className="table-wrap" style={{ maxHeight: "none" }}>
      <table className="tbl">
        <thead>
          <tr>
            <th style={{ width: 46 }}>#</th>
            <th>Code</th>
            <th>Milestone</th>
            <th>Category</th>
            <th>Owner role</th>
            <th className="right">Offset (wd)</th>
            <th className="right">Duration</th>
            <th>Depends on</th>
            <th className="center">Critical</th>
            <th className="center">Approval</th>
            <th>Evidence source</th>
          </tr>
        </thead>
        <tbody>
          {milestones.map((m) => (
            <tr key={m.code}>
              <td className="num muted">{m.seq}</td>
              <td className="cell-code">{m.code}</td>
              <td>{m.name}</td>
              <td><span className="badge">{m.category}</span></td>
              <td style={{ fontSize: 12 }}>{m.owner_role}</td>
              <td className="right mono">{m.offset_days}</td>
              <td className="right mono">{m.duration_days}</td>
              <td className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
                {(m.depends_on || []).length ? m.depends_on.join(", ") : DASH}
              </td>
              <td className="center">{m.is_critical ? <span style={{ color: "var(--primary)" }}>◆</span> : <span className="muted">—</span>}</td>
              <td className="center">{m.requires_approval ? "✓" : <span className="muted">—</span>}</td>
              <td style={{ fontSize: 11, color: "var(--text-muted)", maxWidth: 240 }}>{m.evidence_source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
