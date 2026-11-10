import type { ReactNode } from "react";
import { X } from "lucide-react";
import StatusBadge from "./StatusBadge";
import DependencyChain from "./DependencyChain";
import UpdateMilestoneForm, { type UpdateFormValue } from "./UpdateMilestoneForm";
import { fmtDate, fmtWdays, DASH } from "../lib/format";
import type { TnaMilestone } from "../types";

function KV({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="kv">
      <div className="kv-k">{k}</div>
      <div className={`kv-v${mono ? " mono" : ""}`}>{v === null || v === undefined || v === "" ? DASH : v}</div>
    </div>
  );
}

export default function MilestoneDetailDrawer({
  milestone, milestones, onClose, onSubmitUpdate, onSelectCode, busy,
}: {
  milestone: TnaMilestone | null;
  milestones: TnaMilestone[];
  onClose: () => void;
  onSubmitUpdate: (m: TnaMilestone, v: UpdateFormValue) => void;
  onSelectCode: (code: string) => void;
  busy?: boolean;
}) {
  if (!milestone) return null;
  const m = milestone;

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={`Milestone ${m.code}`}>
        <div className="drawer-head">
          <div style={{ flex: 1 }}>
            <div className="row" style={{ gap: 8 }}>
              <span className="badge badge-mono">{m.seq}</span>
              <span className="mono" style={{ fontWeight: 600, color: "var(--primary)" }}>{m.code}</span>
              {m.is_critical && <span className="badge badge-primary" title="On the critical path">◆ Critical path</span>}
              {m.requires_approval && <span className="badge badge-warning">requires approval</span>}
            </div>
            <h3 style={{ fontSize: 18, marginTop: 6 }}>{m.name}</h3>
            <div className="row" style={{ gap: 8, marginTop: 6 }}>
              <StatusBadge status={m.status} />
              <span className="badge">{m.category}</span>
              {m.status_source === "override" && <span className="chip">manual override</span>}
            </div>
          </div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <div className="drawer-body">
          <div className="drawer-section">
            <h4>Schedule</h4>
            <KV k="Planned" v={<>{fmtDate(m.planned_start)} → {fmtDate(m.planned_finish)}</>} mono />
            <KV k="Actual" v={<>{fmtDate(m.actual_start)} → {fmtDate(m.actual_finish)}</>} mono />
            <KV k="Delay (planned → actual)" v={
              m.actual_finish
                ? <span style={{ color: m.delay_days > 0 ? "var(--error)" : m.delay_days < 0 ? "var(--success)" : undefined }}>{fmtWdays(m.delay_days)}</span>
                : DASH
            } mono />
            <KV k="Forecast finish" v={fmtDate(m.forecast_finish)} mono />
            <KV k="Revised finish (re-plan)" v={fmtDate(m.revised_finish)} mono />
            <KV k="Float (working days)" v={m.float_days === null || m.float_days === undefined ? DASH : `${m.float_days} wd`} mono />
            <KV k="Progress" v={`${Math.round(m.progress_pct ?? 0)}%`} mono />
            <KV k="Critical path" v={
              m.is_critical
                ? (m.is_critical_template ? "Computed + template" : "Computed from dependencies")
                : (m.is_critical_template ? "Template flag only" : "No")
            } />
            <KV k="Working calendar" v={m.calendar} mono />
            <KV k="Offset (working days)" v={fmtWdays(m.offset_days)} mono />
            <KV k="Duration" v={`${m.duration_days} day${m.duration_days === 1 ? "" : "s"}`} mono />
            <KV k="Owner" v={m.owner || m.owner_role} />
            <KV k="Owner role (template)" v={m.owner_role} />
            <KV k="Delay reason" v={m.delay_reason} />
            <KV k="Note" v={m.note} />
          </div>

          <div className="drawer-section">
            <h4>Evidence &amp; provenance</h4>
            <KV k="Evidence source" v={m.evidence_source} />
            <KV k="Evidence value" v={m.evidence_value} mono />
            <KV k="Tracking" v={m.manual ? "Manual — no ERP source on this milestone" : "ERP-linked (auto-fed when the document exists)"} />
            <KV k="Retrieved from ERP" v={m.evidence_retrieved ? "Yes" : "No"} />
            <KV k="Data source" v={<span className="badge badge-mono">{m.data_source}</span>} />
            <KV k="Last overlay update" v={fmtDate(m.updated_at)} mono />
          </div>

          <div className="drawer-section">
            <h4>Dependency chain</h4>
            <DependencyChain code={m.code} milestones={milestones} />
            {(m.depends_on || []).length > 0 && (
              <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
                {m.depends_on.map((d) => (
                  <button key={d} className="chip clickable" onClick={() => onSelectCode(d)}>{d}</button>
                ))}
              </div>
            )}
          </div>

          <div className="drawer-section">
            <h4>Record / update (preview-first)</h4>
            <UpdateMilestoneForm milestone={m} onSubmit={(v) => onSubmitUpdate(m, v)} busy={busy} />
          </div>
        </div>

        <div className="drawer-foot">
          <button className="btn btn-secondary" onClick={onClose}>Close</button>
        </div>
      </aside>
    </>
  );
}
