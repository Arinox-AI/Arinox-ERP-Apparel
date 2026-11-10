import { useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import KpiCard from "./KpiCard";
import { fmtDate } from "../lib/format";
import type { AlertItem, AlertSeverity, AlertSummary } from "../types";

const SEV_TONE: Record<AlertSeverity, "red" | "amber" | "navy" | "muted"> = {
  critical: "red", high: "red", medium: "amber", low: "muted",
};

const KIND_LABEL: Record<string, string> = {
  overdue: "Overdue",
  blocked: "Blocked",
  at_risk: "At risk",
  awaiting_approval: "Awaiting approval",
  awaiting_material: "Awaiting material",
  not_recorded: "Not recorded",
  missing_reason: "Missing reason",
};

function AlertCard({ a, onSelect }: { a: AlertItem; onSelect: (code: string) => void }) {
  const sev = SEV_TONE[a.severity] ?? "muted";
  return (
    <div className={`exc-card sev-${sev}`}>
      <div className="exc-rank">{a.severity === "critical" ? "!" : a.escalation_level ? `L${a.escalation_level}` : "·"}</div>
      <div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className="exc-name">{a.name}</span>
          <span className="mono muted" style={{ fontSize: 12 }}>{a.code}</span>
          {a.is_critical && <span className="badge badge-primary" title="Critical path">◆</span>}
          <span className="badge" style={{ textTransform: "uppercase", fontSize: 10 }}>{a.severity}</span>
          <span className="chip" style={{ fontSize: 10 }}>{KIND_LABEL[a.kind] || a.kind}</span>
        </div>
        <div className="exc-meta">
          <span>{a.category}</span>
          <span>·</span>
          <span>owner {a.assigned_to}</span>
          <span>·</span>
          <span>planned {fmtDate(a.planned_finish)}</span>
          {a.days_open > 0 && <><span>·</span><span>{a.days_open} wd open</span></>}
          {a.escalate_to && <><span>·</span><span>escalate L{a.escalation_level} → {a.escalate_to}</span></>}
        </div>
        <div className="exc-action">{a.next_action_text}</div>
        {a.tags.length > 0 && (
          <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
            {a.tags.map((t) => <span key={t} className="chip" style={{ fontSize: 10 }}>{t.replace(/_/g, " ")}</span>)}
          </div>
        )}
      </div>
      <div className="stack-sm" style={{ alignItems: "flex-end" }}>
        <StatusBadge status={a.status} />
        <button className="btn btn-ghost btn-sm" onClick={() => onSelect(a.code)}>Open ▸</button>
      </div>
    </div>
  );
}

export default function AlertsPanel({
  alerts, summary, onSelect, onCopyDigest, digestBusy,
}: {
  alerts: AlertItem[];
  summary: AlertSummary;
  onSelect: (code: string) => void;
  onCopyDigest: () => void;
  digestBusy?: boolean;
}) {
  const [sev, setSev] = useState<"all" | AlertSeverity>("all");
  const [kind, setKind] = useState<string>("all");

  const kinds = useMemo(() => Array.from(new Set(alerts.map((a) => a.kind))), [alerts]);
  const shown = useMemo(
    () => alerts.filter((a) => (sev === "all" || a.severity === sev) && (kind === "all" || a.kind === kind)),
    [alerts, sev, kind]
  );

  return (
    <div className="stack">
      <section className="kpi-row">
        <KpiCard label="Open alerts" value={summary.total} tone={summary.total ? "red" : "green"}
          sub={`${summary.escalation_level_3} at escalation L3`} />
        <KpiCard label="Critical" value={summary.critical} tone={summary.critical ? "red" : "green"}
          sub={`${summary.high} high`} />
        <KpiCard label="Unassigned" value={summary.unassigned} tone={summary.unassigned ? "amber" : "green"}
          sub="no owner on the milestone" />
        <KpiCard label="Missing reason" value={summary.missing_reason} tone={summary.missing_reason ? "amber" : "green"}
          sub="late without a cause" />
        <KpiCard label="Manual (unrecorded)" value={summary.manual} tone="navy" sub="no ERP evidence source" />
        <KpiCard label="Top owner" value={<span style={{ fontSize: 16 }}>{summary.top_owner || "—"}</span>} tone="teal"
          sub="most open milestones" />
      </section>

      <div className="toolbar">
        <span className="muted" style={{ fontSize: 12 }}>Filters</span>
        {(["all", "critical", "high", "medium", "low"] as const).map((s) => (
          <button key={s} className={`chip clickable${sev === s ? " on" : ""}`} onClick={() => setSev(s)}>
            {s === "all" ? "All severity" : s}
          </button>
        ))}
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="all">All kinds</option>
          {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k] || k}</option>)}
        </select>
        <span className="grow" style={{ flex: 1 }} />
        <button className="btn btn-secondary btn-sm" onClick={onCopyDigest} disabled={digestBusy}>
          {digestBusy ? "Building…" : "Copy reminder digest"}
        </button>
        <span className="muted mono" style={{ fontSize: 12 }}>{shown.length}/{alerts.length}</span>
      </div>

      {shown.length === 0 ? (
        <div className="empty">
          <div className="empty-title">No alerts</div>
          <div>Nothing matches the current filters.</div>
        </div>
      ) : (
        <div className="exc-list">
          {shown.map((a) => <AlertCard key={a.code} a={a} onSelect={onSelect} />)}
        </div>
      )}
    </div>
  );
}
