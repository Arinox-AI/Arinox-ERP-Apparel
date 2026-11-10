import { useMemo, useState } from "react";
import { Check, CheckCircle2, Eye, ExternalLink, Filter, Loader2, Pencil, Play, RotateCcw, UploadCloud, X } from "lucide-react";
import type { Rec, Risk } from "../types";
import { priorityColor, statusBadge } from "../types";
import { Card, Empty } from "../ui";

type Tab = "pending" | "approved" | "executed" | "all";

export function ActionsView(props: {
  recs: Rec[];
  risks: Risk[];
  onPreview: (r: Rec) => void;
  onApprove: (r: Rec) => void;
  onReject: (r: Rec) => void;
  onExecute: (r: Rec) => void;
  onSubmit: (r: Rec) => void;
  onRollback: (r: Rec) => void;
  busyId?: number | null;
  onModify: (r: Rec) => void;
  onOpenRisk: (r: Risk) => void;
}) {
  const { recs, risks, onPreview, onApprove, onReject, onExecute, onSubmit, onRollback, busyId, onModify, onOpenRisk } = props;
  const [tab, setTab] = useState<Tab>("pending");
  const [q, setQ] = useState("");
  const [priority, setPriority] = useState("all");

  const byRiskId = useMemo(() => {
    const m: Record<number, Risk> = {};
    risks.forEach((r) => { m[r.id] = r; });
    return m;
  }, [risks]);

  const counts = useMemo(() => ({
    pending: recs.filter((r) => r.approval_status === "pending").length,
    approved: recs.filter((r) => r.approval_status === "approved").length,
    executed: recs.filter((r) => r.approval_status === "executed").length,
    all: recs.length,
  }), [recs]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
    return recs
      .filter((r) => (tab === "all" ? true : r.approval_status === tab))
      .filter((r) => (priority === "all" ? true : r.priority === priority))
      .filter((r) => (needle ? JSON.stringify(r).toLowerCase().includes(needle) : true))
      .sort((a, b) => (order[a.priority] ?? 9) - (order[b.priority] ?? 9));
  }, [recs, tab, priority, q]);

  return (
    <>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <div className="tabs">
          {(["pending", "approved", "executed", "all"] as Tab[]).map((t) => (
            <button key={t} className={`tab${tab === t ? " is-active" : ""}`} onClick={() => setTab(t)}>
              {t === "all" ? "All" : t.charAt(0).toUpperCase() + t.slice(1)}
              <span style={{ marginLeft: 6, color: "var(--text-muted)", fontWeight: 700 }}>{counts[t]}</span>
            </button>
          ))}
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-muted)" }}>
          <Filter size={13} />
          <select className="select" value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="all">All priorities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>

        <input
          className="input"
          style={{ marginLeft: "auto", minWidth: 240 }}
          placeholder="Search actions, teams, risks…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <Card flush>
        {rows.length === 0 ? (
          <Empty good icon={<CheckCircle2 size={18} />} title="Nothing here" hint="No recommendations match this filter." />
        ) : (
          rows.map((r) => {
            const st = statusBadge[r.approval_status] || statusBadge.pending;
            const risk = byRiskId[r.risk_id];
            const busy = busyId === r.id;
            return (
              <div key={r.id} className="row" style={{ alignItems: "flex-start" }}>
                <span className="row__rail" style={{ background: priorityColor[r.priority] || "var(--border-strong)" }} />
                <div className="row__main">
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span className="badge" style={{ background: st.bg, color: st.fg }}>{st.label}</span>
                    <span className="badge badge--outline" style={{ textTransform: "capitalize" }}>{r.priority} priority</span>
                    <span className="badge">{r.responsible_team}</span>
                  </div>

                  <div className="row__title" style={{ marginTop: 6 }}>{r.action}</div>
                  {r.expected_impact && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{r.expected_impact}</div>}

                  <button
                    onClick={() => risk && onOpenRisk(risk)}
                    disabled={!risk}
                    style={{ marginTop: 6, border: "none", background: "transparent", padding: 0, fontSize: 11.5, color: "var(--text-muted)", textAlign: "left" }}
                    title={risk ? "Open the risk evidence" : undefined}
                  >
                    Risk: <span style={{ color: "var(--primary)", textDecoration: risk ? "underline" : "none" }}>{r.risk_title}</span>
                  </button>
                </div>

                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center", maxWidth: 320 }}>
                  {busy && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--primary)", fontWeight: 600 }}>
                      <Loader2 size={13} className="spin" /> Working…
                    </span>
                  )}
                  {["pending", "approved", "modified"].includes(r.approval_status) && (
                    <button className="btn btn--sm" onClick={() => onPreview(r)} disabled={busy}><Eye size={12} /> Preview</button>
                  )}
                  {r.approval_status === "pending" && (
                    <>
                      <button className="btn btn--sm btn--positive" onClick={() => onApprove(r)} disabled={busy}><Check size={12} /> Approve &amp; create</button>
                      <button className="btn btn--sm btn--danger" onClick={() => onReject(r)} disabled={busy}><X size={12} /> Reject</button>
                    </>
                  )}
                  {r.approval_status === "approved" && (
                    <button className="btn btn--sm btn--primary" onClick={() => onExecute(r)} disabled={busy}><Play size={12} /> Execute</button>
                  )}
                  {r.write_status === "created" && (
                    <button className="btn btn--sm btn--brand" onClick={() => onSubmit(r)} disabled={busy} title="Confirm this draft in the ERP (docstatus 0 → 1)">
                      {busy ? <Loader2 size={12} className="spin" /> : <UploadCloud size={12} />} Submit in ERP
                    </button>
                  )}
                  {r.write_status === "submitted" && (
                    <span className="badge" style={{ background: "var(--positive-light)", color: "var(--positive-ink)" }}>Submitted in ERP</span>
                  )}
                  {["created", "submitted"].includes(r.write_status || "") && (
                    <button className="btn btn--sm btn--ghost" onClick={() => onRollback(r)} disabled={busy}
                            title="Reverse this action: delete the draft, or cancel the submitted record, and reopen the risk">
                      <RotateCcw size={12} /> Roll back
                    </button>
                  )}
                  {r.erp_url && (
                    <a className="btn btn--sm" href={r.erp_url} target="_blank" rel="noreferrer"
                       title="Open this record in KOGO ERP to add the remaining details and submit">
                      <ExternalLink size={12} /> Open in ERP
                    </a>
                  )}
                  {r.approval_status !== "executed" && (
                    <button className="btn btn--sm btn--ghost" onClick={() => onModify(r)} disabled={busy} title="Modify wording"><Pencil size={12} /></button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </Card>

      <div style={{ marginTop: 12, fontSize: 11.5, color: "var(--text-muted)" }}>
        Previews are read-only. Executions perform a real, reversible ERP write (drafts only) and are
        recorded in the audit log.
      </div>
    </>
  );
}
