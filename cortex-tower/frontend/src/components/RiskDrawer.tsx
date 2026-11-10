import { useState } from "react";
import { Sparkles, Eye, Check, X, Pencil, Play, Loader2, UploadCloud, ExternalLink } from "lucide-react";
import { Drawer, KV } from "../ui";
import type { Rec, Risk } from "../types";
import { RISK_FIELD_ORDER, RISK_TYPE_META, fmtDate, priorityColor, statusBadge } from "../types";

export function RiskDrawer(props: {
  risk: Risk;
  recs: Rec[];
  onClose: () => void;
  onPreview: (r: Rec) => void;
  onApprove: (r: Rec) => void;
  onReject: (r: Rec) => void;
  onExecute: (r: Rec) => void;
  onSubmit: (r: Rec) => void;
  busyId?: number | null;
  onModify: (r: Rec) => void;
  onAsk: (q: string) => void;
}) {
  const { risk, recs, onClose, onPreview, onApprove, onReject, onExecute, onSubmit, busyId, onModify, onAsk } = props;
  const meta = RISK_TYPE_META[risk.risk_type] || { label: risk.risk_type, hint: "" };
  const [showAllOrders, setShowAllOrders] = useState(false);

  const kvItems = RISK_FIELD_ORDER
    .map(({ key, label }) => ({ k: label, v: risk[key] as string | undefined }))
    .filter((it) => it.v !== undefined && it.v !== null && String(it.v).trim() !== "")
    .map((it) => ({ k: it.k, v: it.k.toLowerCase().includes("date") ? fmtDate(String(it.v)) : String(it.v) }));

  const orders = risk.affected_orders || [];
  const shownOrders = showAllOrders ? orders : orders.slice(0, 6);

  return (
    <Drawer
      onClose={onClose}
      title={risk.title}
      sub={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className={`badge badge--${risk.severity === "critical" ? "critical" : "warning"}`}>
            <span className="badge__dot" />
            {risk.severity === "critical" ? "Critical" : "Warning"}
          </span>
          <span className="badge badge--outline">{meta.label}</span>
          {meta.hint && <span style={{ color: "var(--text-muted)" }}>{meta.hint}</span>}
        </span>
      }
      footer={
        <>
          <button className="btn btn--ghost" onClick={() => onAsk(`What should we do about ${risk.title}?`)}>
            <Sparkles size={13} /> Ask KOGO
          </button>
          <button className="btn" onClick={onClose}>Close</button>
        </>
      }
    >
      <div className="card" style={{ boxShadow: "none", background: "var(--surface-hover)" }}>
        <div className="card__body">
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 12 }}>
            Live evidence from KOGO ERP
          </div>
          <KV items={kvItems} />
        </div>
      </div>

      {risk.ai && (
        <div className="card" style={{ marginTop: 18, border: "1px solid var(--brand, #3b6fe0)" }}>
          <div className="card__body">
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--brand, #3b6fe0)" }}>
                <Sparkles size={11} style={{ verticalAlign: -1 }} /> AI next steps
              </span>
              <span className="badge" style={{ background: risk.ai.grounded ? "var(--positive-light)" : "var(--warning-light)", color: risk.ai.grounded ? "var(--positive-ink)" : "var(--warning-ink)" }}>
                {risk.ai.grounded ? "Grounded" : "Review — unsourced"}
              </span>
            </div>
            {risk.ai.reasoning && (
              <div style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--text-secondary)", marginBottom: 10 }}>{risk.ai.reasoning}</div>
            )}
            {(risk.ai.actions || []).map((a, i) => (
              <div key={i} style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", color: priorityColor[a.priority || "medium"] || "var(--text-muted)" }}>{a.priority}</span>
                  {a.owner && <span className="badge badge--outline">{a.owner}</span>}
                  {typeof a.confidence === "number" && <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--text-muted)" }}>confidence {Math.round(a.confidence * 100)}%</span>}
                </div>
                <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 4, lineHeight: 1.4 }}>{a.action}</div>
                {a.why && <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>{a.why}</div>}
              </div>
            ))}
            {risk.ai.predicted_impact && (
              <div style={{ fontSize: 11.5, color: "var(--text-secondary)", marginTop: 10 }}><b>Predicted impact:</b> {risk.ai.predicted_impact}</div>
            )}
            {risk.ai.watch_outs && (
              <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 4 }}><b>Watch out:</b> {risk.ai.watch_outs}</div>
            )}
          </div>
        </div>
      )}

      {orders.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 8 }}>
            Affected records ({orders.length})
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {shownOrders.map((o) => (
              <span key={o} className="badge badge--outline" style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 10.5 }}>{o}</span>
            ))}
            {orders.length > 6 && (
              <button className="btn btn--sm btn--ghost" onClick={() => setShowAllOrders((v) => !v)}>
                {showAllOrders ? "Show less" : `+${orders.length - 6} more`}
              </button>
            )}
          </div>
        </div>
      )}

      <div style={{ marginTop: 22 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 8 }}>
          Recommended actions for this risk ({recs.length})
        </div>
        {recs.length === 0 && (
          <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
            This risk has been resolved — no further action is offered.
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {recs.map((r) => {
            const st = statusBadge[r.approval_status] || statusBadge.pending;
            return (
              <div key={r.id} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: priorityColor[r.priority] || "var(--text-muted)", textTransform: "uppercase" }}>
                    {r.priority}
                  </span>
                  <span className="badge" style={{ background: st.bg, color: st.fg }}>{st.label}</span>
                  <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>{r.responsible_team}</span>
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4 }}>{r.action}</div>
                {r.expected_impact && (
                  <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 3 }}>Impact: {r.expected_impact}</div>
                )}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 10 }}>
                  {busyId === r.id && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--primary)", fontWeight: 600 }}>
                      <Loader2 size={13} className="spin" /> Working…
                    </span>
                  )}
                  {["pending", "approved", "modified"].includes(r.approval_status) && (
                    <button className="btn btn--sm" onClick={() => onPreview(r)} disabled={busyId === r.id}><Eye size={12} /> Preview</button>
                  )}
                  {r.approval_status === "pending" && (
                    <>
                      <button className="btn btn--sm btn--positive" onClick={() => onApprove(r)} disabled={busyId === r.id}><Check size={12} /> Approve &amp; create</button>
                      <button className="btn btn--sm btn--danger" onClick={() => onReject(r)} disabled={busyId === r.id}><X size={12} /> Reject</button>
                    </>
                  )}
                  {r.approval_status === "approved" && (
                    <button className="btn btn--sm btn--primary" onClick={() => onExecute(r)} disabled={busyId === r.id}><Play size={12} /> Execute</button>
                  )}
                  {r.write_status === "created" && (
                    <button className="btn btn--sm btn--brand" onClick={() => onSubmit(r)} disabled={busyId === r.id} title="Confirm this draft in the ERP (docstatus 0 → 1)">
                      <UploadCloud size={12} /> Submit in ERP
                    </button>
                  )}
                  {r.write_status === "submitted" && (
                    <span className="badge" style={{ background: "var(--positive-light)", color: "var(--positive-ink)" }}>Submitted in ERP</span>
                  )}
                  {r.erp_url && (
                    <a className="btn btn--sm" href={r.erp_url} target="_blank" rel="noreferrer"
                       title="Open this record in KOGO ERP to add the remaining details and submit">
                      <ExternalLink size={12} /> Open in ERP
                    </a>
                  )}
                  <button className="btn btn--sm btn--ghost" onClick={() => onModify(r)} disabled={busyId === r.id}><Pencil size={12} /> Modify</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ marginTop: 22, fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
        Integration — previews and executions are recorded in the dashboard audit log.
        Executions perform a <b>real, reversible ERP write (drafts only)</b>; nothing is submitted
        without approval.
      </div>
    </Drawer>
  );
}
