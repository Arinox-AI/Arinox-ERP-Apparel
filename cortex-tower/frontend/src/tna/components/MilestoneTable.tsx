import { useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import { fmtDate, fmtWdays, DASH } from "../lib/format";
import type { TnaMilestone } from "../types";

type SortKey = "seq" | "planned_finish" | "status" | "delay_days" | "category" | "float_days";

export default function MilestoneTable({
  milestones, selectedCode, onSelect,
}: {
  milestones: TnaMilestone[];
  selectedCode: string | null;
  onSelect: (code: string) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("seq");
  const [asc, setAsc] = useState(true);

  const rows = useMemo(() => {
    const copy = [...milestones];
    copy.sort((a, b) => {
      let r = 0;
      switch (sortKey) {
        case "seq": r = a.seq - b.seq; break;
        case "category": r = a.category.localeCompare(b.category) || a.seq - b.seq; break;
        case "status": r = a.status.localeCompare(b.status) || a.seq - b.seq; break;
        case "delay_days": r = a.delay_days - b.delay_days; break;
        case "float_days": r = (a.float_days ?? 9999) - (b.float_days ?? 9999); break;
        case "planned_finish": r = (a.planned_finish || "").localeCompare(b.planned_finish || ""); break;
      }
      return asc ? r : -r;
    });
    return copy;
  }, [milestones, sortKey, asc]);

  const clickSort = (k: SortKey) => {
    if (k === sortKey) setAsc(!asc);
    else { setSortKey(k); setAsc(true); }
  };
  const arrow = (k: SortKey) => (sortKey === k ? (asc ? " ▲" : " ▼") : "");

  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th className="sortable" onClick={() => clickSort("seq")} style={{ width: 46 }}>#{arrow("seq")}</th>
            <th>Milestone</th>
            <th className="sortable" onClick={() => clickSort("category")}>Category{arrow("category")}</th>
            <th>Owner</th>
            <th>Planned start</th>
            <th className="sortable" onClick={() => clickSort("planned_finish")}>Planned finish{arrow("planned_finish")}</th>
            <th>Actual start</th>
            <th>Actual finish</th>
            <th className="sortable right" onClick={() => clickSort("delay_days")}>Delay{arrow("delay_days")}</th>
            <th className="sortable right" onClick={() => clickSort("float_days")} title="Total float in working days (computed from the dependency graph). 0 = on the critical path.">Float{arrow("float_days")}</th>
            <th className="right" title="Completion percentage">Prog</th>
            <th className="sortable" onClick={() => clickSort("status")}>Status{arrow("status")}</th>
            <th>Evidence source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr
              key={m.code}
              className={`clickable${selectedCode === m.code ? " selected" : ""}`}
              onClick={() => onSelect(m.code)}
              title="Open milestone detail"
            >
              <td className="num muted">{m.seq}</td>
              <td>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {m.is_critical && <span style={{ color: "var(--primary)" }} title={m.is_critical_template ? "Critical path (computed + template)" : "Critical path (computed)"}>◆</span>}
                  <div>
                    <div style={{ fontWeight: 500 }}>{m.name}</div>
                    <div className="cell-code muted">{m.code}</div>
                  </div>
                  {m.manual ? (
                    <span className="chip" title="No ERP evidence source — updated manually" style={{ fontSize: 10 }}>manual</span>
                  ) : (
                    <span className="chip" title="Auto-fed from the ERP" style={{ fontSize: 10 }}>ERP</span>
                  )}
                </div>
              </td>
              <td><span className="badge">{m.category}</span></td>
              <td style={{ fontSize: 12 }}>{m.owner || m.owner_role}</td>
              <td className="date">{fmtDate(m.planned_start)}</td>
              <td className="date">{fmtDate(m.planned_finish)}</td>
              <td className="date">{fmtDate(m.actual_start)}</td>
              <td className="date">{fmtDate(m.actual_finish)}</td>
              <td className="right">
                {m.actual_finish ? (
                  <span className="mono" style={{ color: m.delay_days > 0 ? "var(--error)" : m.delay_days < 0 ? "var(--success)" : "var(--text-muted)" }}>
                    {fmtWdays(m.delay_days)}
                    {m.needs_attribution && <span title="Late with no delay reason recorded" style={{ color: "var(--warning)", marginLeft: 4 }}>⚑</span>}
                  </span>
                ) : (
                  <span className="muted">{DASH}</span>
                )}
              </td>
              <td className="right">
                {m.float_days === null || m.float_days === undefined ? (
                  <span className="muted">—</span>
                ) : (
                  <span className="mono" style={{ color: m.float_days <= 0 ? "var(--primary)" : "var(--text-muted)" }}>{m.float_days} wd</span>
                )}
              </td>
              <td className="right">
                <span className="mono" style={{ color: (m.progress_pct ?? 0) >= 100 ? "var(--success)" : "var(--text-muted)" }}>
                  {m.progress_pct === null || m.progress_pct === undefined ? "—" : `${Math.round(m.progress_pct)}%`}
                </span>
              </td>
              <td>
                <div className="row" style={{ gap: 6 }}>
                  <StatusBadge status={m.status} />
                  {m.status_source === "override" && <span className="chip" title="Status set manually (override)">manual</span>}
                </div>
              </td>
              <td style={{ fontSize: 11, color: "var(--text-muted)", maxWidth: 220 }}>{m.evidence_source || DASH}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={13} className="center muted" style={{ padding: 30 }}>No milestones match the current filters.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
