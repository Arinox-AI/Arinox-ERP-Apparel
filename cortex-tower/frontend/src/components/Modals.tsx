import React, { useState } from "react";
import { X, Mail, FileText, AlertTriangle, Sparkles, Send, Loader2, CheckCircle2, ExternalLink, UploadCloud } from "lucide-react";
import { Modal } from "../ui";
import { callApi } from "../services/api";
import type { Rec, Risk } from "../types";

/* ── Done modal — a DRAFT was created; pivot the user into the ERP ───────── */
export function DoneModal({ d, onClose, onSubmit, busy }: {
  d: any;
  onClose: () => void;
  onSubmit?: () => void;
  busy?: boolean;
}) {
  const write = d?.write || {};
  const doctype = d?.erp_doctype || write.doctype || "record";
  const docs: string[] = Array.isArray(write.docs) ? write.docs : (write.doc ? [write.doc] : []);
  const count = docs.length || Number(write.count) || 1;
  const url = d?.erp_url;
  return (
    <Modal onClose={onClose} width={560}>
      <div className="card__head">
        <div>
          <div className="card__title">Draft created in KOGO ERP</div>
          <div className="card__sub">Final confirmation happens in the ERP</div>
        </div>
        <button className="btn btn--ghost btn--icon" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close"><X size={16} /></button>
      </div>
      <div className="card__body" style={{ display: "grid", gap: 14 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-start", fontSize: 13, lineHeight: 1.55 }}>
          <CheckCircle2 size={18} color="var(--positive-ink)" style={{ marginTop: 2, flex: "0 0 auto" }} />
          <div>
            Created <b>{count > 1 ? `${count} × ` : ""}{doctype}</b>
            {count === 1 && docs[0] ? <> — <code>{docs[0]}</code></> : null} as a <b>draft</b>.
            <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 5 }}>
              Nothing is final yet. Open it in the ERP to add the remaining details
              (payment reference, warehouse, dates…) and submit — or use <b>Submit in ERP</b>.
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {url && (
            <a className="btn btn--primary" href={url} target="_blank" rel="noreferrer">
              <ExternalLink size={13} /> Open in ERP to finish
            </a>
          )}
          {onSubmit && (
            <button className="btn" onClick={onSubmit} disabled={busy}>
              {busy ? <Loader2 size={13} className="spin" /> : <UploadCloud size={13} />} Submit in ERP
            </button>
          )}
          <button className="btn btn--ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </Modal>
  );
}

/* ── Preview modal (email or ERP draft) ─────────────────────────────────── */
export function PreviewModal({ d, rec, onConfirm, onClose, notify, onQueued }: {
  d: any;
  rec: Rec;
  onConfirm: () => void;
  onClose: () => void;
  notify?: (msg: string) => void;
  onQueued?: () => void;
}) {
  const isEmail = d.channel === "email";
  const isErp = d.channel === "erp";
  const title = isEmail ? "Email preview" : isErp ? "ERP draft record" : "Action preview";
  const canQueue = isEmail && !d.blocked && !!d.email;
  const [queuing, setQueuing] = useState(false);

  const queueForApproval = async () => {
    if (queuing) return;
    setQueuing(true);
    try {
      const res = await callApi("create_email_draft", { action_id: rec.id });
      const data: any = res.data || {};
      if (res.success && data.ok) {
        notify?.("Queued for approval — see Outbound Mail.");
        onQueued?.();
      } else if (data.blocked) {
        notify?.(`Not queued: ${data.blocked_reason || "the engine blocked this message."}`);
      } else {
        notify?.(data.blocked_reason || res.message || "Could not queue this email for approval.");
      }
    } catch {
      notify?.("Could not reach the middleware — the email was not queued.");
    } finally {
      setQueuing(false);
    }
  };

  return (
    <Modal onClose={onClose} width={600}>
      <div className="card__head">
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ display: "grid", placeItems: "center", width: 28, height: 28, borderRadius: 8, background: "var(--primary-light)", color: "var(--primary)" }}>
            {isEmail ? <Mail size={14} /> : isErp ? <FileText size={14} /> : <Sparkles size={14} />}
          </span>
          <div>
            <div className="card__title">{title}</div>
            <div className="card__sub">{rec.risk_title}</div>
          </div>
        </div>
        <button className="btn btn--ghost btn--icon" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close"><X size={16} /></button>
      </div>

      <div className="card__body">
        <div style={{ background: "var(--primary-light)", border: "1px solid #cfdcea", borderRadius: "var(--radius-md)", padding: "10px 14px", fontSize: 12.5, color: "var(--primary)", marginBottom: 12, display: "flex", gap: 8 }}>
          <Sparkles size={14} style={{ flex: "0 0 14px", marginTop: 2 }} />
          <span><b>Cortex OS intends to:</b> {d.intent}</span>
        </div>

        {d.blocked && (
          <div style={{ display: "flex", gap: 8, padding: "10px 14px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "var(--radius-md)", fontSize: 12.5, color: "#991b1b", marginBottom: 16 }}>
            <AlertTriangle size={14} style={{ flex: "0 0 14px", marginTop: 2 }} />
            <span>
              <b>Generation blocked — nothing was produced.</b> {d.blocked_message}
              {Array.isArray(d.blocked_detail) && d.blocked_detail.length > 0 && (
                <span> ({d.blocked_detail.join(", ")})</span>
              )}
            </span>
          </div>
        )}

        {!d.blocked && d.grounding && (
          <div style={{ display: "flex", gap: 8, padding: "8px 14px", background: d.grounding.ok ? "#f0fdf4" : "#fffbeb", border: `1px solid ${d.grounding.ok ? "#86efac" : "#fcd34d"}`, borderRadius: "var(--radius-md)", fontSize: 12, color: d.grounding.ok ? "#166534" : "#92400e", marginBottom: 16 }}>
            <span>
              {d.grounding.ok ? "✓ Grounded in live records" : "Needs review — could not be fully traced"}
              {d.grounding.fell_back ? " · details withheld" : ""}
              {d.comm_type ? ` · ${d.comm_type}` : ""}
              {d.party_status === "unconfirmed" ? " · recipient unconfirmed" : ""}
              {d.policy_version ? ` · ${d.policy_version}` : ""}
            </span>
          </div>
        )}

        {isEmail && d.email && (
          <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
            <div style={{ padding: "10px 14px", background: "var(--surface-hover)", borderBottom: "1px solid var(--border)", fontSize: 12.5 }}>
              <Row k="From" v={d.email.from} />
              <Row k="To" v={d.email.to} />
              <Row k="Subject" v={d.email.subject} strong />
            </div>
            <div style={{ padding: 14, fontSize: 12.5, whiteSpace: "pre-wrap", color: "var(--text-secondary)", lineHeight: 1.65 }}>{d.email.body}</div>
          </div>
        )}

        {isErp && d.record && (
          <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
            <div style={{ padding: "10px 14px", background: "var(--surface-hover)", borderBottom: "1px solid var(--border)", fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)" }}>
              {d.record.doctype}
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <tbody>
                {Object.entries(d.record.fields || {}).map(([k, v]) => (
                  <tr key={k} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "8px 14px", color: "var(--text-muted)", width: 170, verticalAlign: "top" }}>{k.replace(/_/g, " ")}</td>
                    <td style={{ padding: "8px 14px", fontWeight: 500 }}>{String(v ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!isEmail && !isErp && (
          <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>This action would be executed directly by Cortex OS.</div>
        )}

        <div style={{ marginTop: 16, display: "flex", gap: 8, padding: "10px 14px", background: "var(--warning-light)", border: "1px solid #fcd34d", borderRadius: "var(--radius-md)", fontSize: 12, color: "var(--warning-ink)" }}>
          <AlertTriangle size={14} style={{ flex: "0 0 14px", marginTop: 2 }} />
          Step 1 of 2 — preview only, nothing is written yet. You'll confirm on the next step.
        </div>
      </div>

      <div className="drawer__foot">
        <button className="btn" onClick={onClose}>Cancel</button>
        {canQueue && (
          <button className="btn btn--brand" onClick={queueForApproval} disabled={queuing}>
            {queuing ? <Loader2 size={14} className="spin" /> : <Send size={14} />} Queue for approval
          </button>
        )}
        <button className="btn btn--primary" onClick={onConfirm}>Continue →</button>
      </div>
    </Modal>
  );
}

function Row({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 3 }}>
      <span style={{ color: "var(--text-muted)", minWidth: 58 }}>{k}</span>
      <span style={{ fontWeight: strong ? 600 : 400, color: "var(--text-secondary)" }}>{v}</span>
    </div>
  );
}

/* ── Intent & data confirmation ─────────────────────────────────────────── */
export interface FormField {
  key: string; label: string; type: string; required?: boolean;
  options?: string[]; default?: any; help?: string;
}
export interface InputSpec { fields: FormField[]; values: Record<string, any>; missing: string[]; }

export function IntentModal(props: {
  rec: Rec; risk: Risk; actionLabel: string; erpDoctype?: string;
  inputs?: InputSpec;
  onPreview: () => void; onApprove: (values: Record<string, any>) => void; onClose: () => void;
}) {
  const { rec, risk, actionLabel, erpDoctype, inputs, onPreview, onApprove, onClose } = props;
  const fields = inputs?.fields ?? [];
  const [vals, setVals] = useState<Record<string, any>>(() => ({ ...(inputs?.values ?? {}) }));
  React.useEffect(() => { setVals({ ...(inputs?.values ?? {}) }); }, [inputs]);
  const set = (k: string, v: any) => setVals((p) => ({ ...p, [k]: v }));
  const missing = fields.filter((f) => f.required && !String(vals[f.key] ?? "").trim());
  const ready = missing.length === 0;

  const rows: [string, string][] = [
    ["Risk", risk.title],
    ["Recommended action", rec.action],
    ["Expected impact", rec.expected_impact],
    ["Responsible team", rec.responsible_team],
    ["Priority", rec.priority],
  ];
  if (risk.material) rows.push(["Material", risk.material]);
  if (risk.required_qty) rows.push(["Required qty", risk.required_qty]);
  if (risk.affected_orders?.length) rows.push(["Affected orders", risk.affected_orders.join(", ")]);
  if (erpDoctype) rows.unshift(["Creates in ERP", erpDoctype]);

  const field = (f: FormField) => {
    const v = vals[f.key] ?? "";
    const common = { value: v, onChange: (e: any) => set(f.key, e.target.value) };
    let control;
    if (f.type === "select") {
      control = (
        <select className="input" {...common}>
          <option value="">— select —</option>
          {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    } else if (f.type === "textarea") {
      control = <textarea className="input" rows={2} {...common} />;
    } else {
      control = <input className="input" type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"} {...common} />;
    }
    return (
      <div key={f.key} style={{ marginBottom: 10 }}>
        <label style={{ display: "block", fontSize: 11, fontWeight: 700, letterSpacing: 0.4,
                        textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 5 }}>
          {f.label}{f.required ? <span style={{ color: "var(--danger, #d92d20)" }}> *</span> : null}
        </label>
        {control}
        {f.help ? <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{f.help}</div> : null}
      </div>
    );
  };

  return (
    <Modal onClose={onClose} width={580}>
      <div className="card__head">
        <div>
          <div className="card__title">Confirm action</div>
          <div className="card__sub">{risk.severity === "critical" ? "Critical risk" : "Warning risk"}</div>
        </div>
        <button className="btn btn--ghost btn--icon" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close"><X size={16} /></button>
      </div>

      <div className="card__body" style={{ maxHeight: "62vh", overflowY: "auto" }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)" }}>Cortex OS intends to</div>
        <div style={{ fontSize: 15, fontWeight: 700, marginTop: 4, marginBottom: 16 }}>{actionLabel}</div>

        {fields.length > 0 && (
          <>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 8 }}>Data entry required</div>
            <div style={{ marginBottom: 16 }}>{fields.map(field)}</div>
          </>
        )}

        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 8 }}>Data that will be used</div>
        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
            <tbody>
              {rows.map(([k, v]) => (
                <tr key={k} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "8px 14px", color: "var(--text-muted)", width: 165, verticalAlign: "top" }}>{k}</td>
                  <td style={{ padding: "8px 14px", fontWeight: 500 }}>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: 16, display: "flex", gap: 8, padding: "10px 14px", background: "var(--warning-light)", border: "1px solid #fcd34d", borderRadius: "var(--radius-md)", fontSize: 12, color: "var(--warning-ink)" }}>
          <AlertTriangle size={14} style={{ flex: "0 0 14px", marginTop: 2 }} />
          Step 2 of 2 — this performs a real, reversible ERP write (a draft record) and is recorded in
          the dashboard audit log. You can roll it back.
        </div>
      </div>

      <div className="drawer__foot">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn--brand" onClick={onPreview}>View preview</button>
        <button className="btn btn--primary" onClick={() => onApprove(vals)} disabled={!ready}
                title={ready ? "" : `Required: ${missing.map((m) => m.label).join(", ")}`}>
          {ready ? "Confirm & execute" : `Fill: ${missing.map((m) => m.label).join(", ")}`}
        </button>
      </div>
    </Modal>
  );
}
