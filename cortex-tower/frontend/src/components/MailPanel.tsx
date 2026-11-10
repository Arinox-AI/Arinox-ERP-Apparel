import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  FlaskConical,
  Inbox,
  Loader2,
  Pencil,
  RefreshCw,
  Save,
  Send,
  Settings,
  Trash2,
  X,
} from "lucide-react";
import { callApi } from "../services/api";
import { Card, Empty, Skel } from "../ui";
import { fmtTime } from "../types";
import type { EmailDraft, MailSettings } from "../types";

/* ── Queue tabs ───────────────────────────────────────────────────────────── */
type QueueTab = "draft" | "sent" | "failed" | "rejected" | "all";

const TABS: { id: QueueTab; label: string }[] = [
  { id: "draft", label: "Awaiting approval" },
  { id: "sent", label: "Sent" },
  { id: "failed", label: "Failed" },
  { id: "rejected", label: "Rejected" },
  { id: "all", label: "All" },
];

const STATUS_BADGE: Record<string, { cls: string; label: string; rail: string }> = {
  draft: { cls: "badge--warning", label: "Draft", rail: "var(--warning)" },
  sent: { cls: "badge--positive", label: "Sent", rail: "var(--positive)" },
  failed: { cls: "badge--critical", label: "Failed", rail: "var(--negative)" },
  rejected: { cls: "badge--outline", label: "Rejected", rail: "var(--border-strong)" },
};

const EMPTY_FORM = {
  email_account: "",
  from_name: "",
  smtp_host: "smtp.gmail.com",
  smtp_port: "587",
  use_tls: true,
  password: "",
  enabled: true,
};

function previewBody(body: string): string {
  const clean = (body || "").trim();
  return clean.length > 320 ? `${clean.slice(0, 320)}…` : clean;
}

/* ── Small labelled field wrapper ─────────────────────────────────────────── */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 5 }}>
      <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)" }}>
        {label}
      </span>
      {children}
    </label>
  );
}

/* ── Outbound mail — approval queue + mail settings ───────────────────────── */
export function MailPanel({ notify }: { notify: (msg: string) => void }) {
  /* queue */
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<QueueTab>("draft");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTo, setEditTo] = useState("");
  const [editSubject, setEditSubject] = useState("");
  const [editBody, setEditBody] = useState("");
  const [sendError, setSendError] = useState<{ id: number; text: string } | null>(null);

  /* settings */
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<MailSettings | null>(null);
  const [connected, setConnected] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const set = (patch: Partial<typeof EMPTY_FORM>) => setForm((f) => ({ ...f, ...patch }));

  /* ── loaders ─────────────────────────────────────────────────────────────── */
  const load = useCallback(async (status: QueueTab) => {
    setLoading(true);
    setError(null);
    try {
      const res = await callApi("get_email_drafts", { status });
      if (res.success && res.data) {
        setDrafts(Array.isArray(res.data.drafts) ? res.data.drafts : []);
      } else {
        setDrafts([]);
        setError(res.message || "Could not load the approval queue.");
      }
    } catch {
      setDrafts([]);
      setError("Could not reach the KOGO middleware.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(tab); }, [tab, load]);

  const loadSettings = useCallback(async () => {
    setSettingsLoading(true);
    try {
      const res = await callApi("get_mail_settings", {});
      if (res.success && res.data) {
        const s: MailSettings = res.data.settings || {};
        setSettings(s);
        setConnected(!!res.data.connected);
        setForm({
          email_account: s.email_account || "",
          from_name: s.from_name || "",
          smtp_host: s.smtp_host || "smtp.gmail.com",
          smtp_port: String(s.smtp_port ?? 587),
          use_tls: !!(s.use_tls ?? true),
          password: "",
          enabled: !!(s.enabled ?? false),
        });
      }
    } catch {
      /* leave the panel in its unavailable state */
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  useEffect(() => { loadSettings(); }, [loadSettings]);

  /* ── queue actions ───────────────────────────────────────────────────────── */
  const approve = async (d: EmailDraft, edits?: { subject: string; body: string; to_email: string }) => {
    const to = (edits?.to_email?.trim() || d.to_email) || "the recipient";
    if (!window.confirm(edits ? `Save your edits and send this email to ${to} now?` : `Send this email to ${to} now?`)) return;
    setBusyId(d.id);
    setSendError(null);
    try {
      // `confirm: 1` is the explicit human go-ahead — the server refuses to send without it.
      const params: Record<string, any> = { draft_id: d.id, confirm: 1 };
      if (edits) {
        params.subject = edits.subject;
        params.body = edits.body;
        params.to_email = edits.to_email.trim();
      }
      const res = await callApi("approve_and_send_email", params);
      const data: any = res.data || {};
      if (res.success && data.ok) {
        notify(`Email sent to ${data.draft?.to_email || to}.`);
        setEditingId(null);
        setSendError(null);
        await load(tab);
      } else if (data.error === "invalid_recipient") {
        setSendError({ id: d.id, text: "Enter a valid email address to send." });
      } else if (data.error === "confirmation_required") {
        notify("Blocked — sending requires your explicit confirmation.");
      } else if (data.error === "ungrounded") {
        notify("Blocked — the message could no longer be traced to live records.");
      } else {
        notify(`Send failed: ${data.error || res.message || "unknown error"}`);
      }
    } catch {
      notify("Could not reach the middleware — the email was not sent.");
    } finally {
      setBusyId(null);
    }
  };

  const reject = async (d: EmailDraft) => {
    const reason = window.prompt(
      `Reject this draft${d.subject ? ` (“${d.subject}”)` : ""}. Reason (optional):`,
      ""
    );
    if (reason === null) return;
    setBusyId(d.id);
    try {
      const res = await callApi("reject_email_draft", { draft_id: d.id, reason });
      if (res.success && (res.data?.ok ?? true)) {
        notify("Draft rejected.");
        setEditingId(null);
        await load(tab);
      } else {
        notify(res.data?.error || res.message || "Could not reject the draft.");
      }
    } catch {
      notify("Could not reach the middleware — the draft was not rejected.");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (d: EmailDraft) => {
    if (!window.confirm("Delete this draft permanently?")) return;
    setBusyId(d.id);
    try {
      const res = await callApi("delete_email_draft", { draft_id: d.id });
      if (res.success) {
        notify("Draft deleted.");
        await load(tab);
      } else {
        notify(res.message || "Could not delete the draft.");
      }
    } catch {
      notify("Could not reach the middleware.");
    } finally {
      setBusyId(null);
    }
  };

  const startEdit = (d: EmailDraft) => {
    setEditingId(d.id);
    setEditTo(d.to_email || "");
    setEditSubject(d.subject || "");
    setEditBody(d.body || "");
    setSendError(null);
  };

  /* ── settings actions ────────────────────────────────────────────────────── */
  const saveSettings = async () => {
    setSaving(true);
    setFeedback(null);
    try {
      const params: Record<string, any> = {
        email_account: form.email_account.trim(),
        from_name: form.from_name.trim(),
        smtp_host: form.smtp_host.trim(),
        smtp_port: Number(form.smtp_port) || 587,
        use_tls: form.use_tls ? 1 : 0,
        enabled: form.enabled ? 1 : 0,
      };
      if (form.password) params.password = form.password;
      const res = await callApi("save_mail_settings", params);
      if (res.success && res.data?.settings) {
        setSettings(res.data.settings);
        setForm((f) => ({ ...f, password: "" }));
        setFeedback({ kind: "ok", text: "Mail settings saved." });
        notify("Mail settings saved.");
      } else {
        setFeedback({ kind: "err", text: res.message || "Could not save the settings." });
      }
    } catch {
      setFeedback({ kind: "err", text: "Could not reach the KOGO middleware." });
    } finally {
      setSaving(false);
    }
  };

  const testSettings = async () => {
    setTesting(true);
    setFeedback(null);
    try {
      const res = await callApi("test_mail_settings", {});
      const data: any = res.data || {};
      if (res.success && data.ok) {
        setFeedback({ kind: "ok", text: `Test email sent${data.to ? ` to ${data.to}` : ""}.` });
        notify("Test email sent.");
      } else {
        const text = data.error || res.message || "Test email failed.";
        setFeedback({ kind: "err", text });
        notify(text);
      }
    } catch {
      setFeedback({ kind: "err", text: "Could not reach the KOGO middleware." });
      notify("Could not reach the middleware.");
    } finally {
      setTesting(false);
    }
  };

  /* ── render ──────────────────────────────────────────────────────────────── */
  return (
    <>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <div className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={`tab${tab === t.id ? " is-active" : ""}`} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        <button className="btn btn--sm" style={{ marginLeft: "auto" }} onClick={() => load(tab)} disabled={loading}>
          <RefreshCw size={13} className={loading ? "spin" : undefined} /> Refresh
        </button>
        <button className="btn btn--sm btn--brand" onClick={() => setSettingsOpen((o) => !o)}>
          <Settings size={13} /> Mail settings {settingsOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      </div>

      {settingsOpen && (
        <Card
          title="Mail settings"
          sub={settings?.email_account ? `Sending as ${settings.email_account}` : "Configure the SMTP account used for outbound mail"}
          actions={
            <span className={`badge ${connected ? "badge--positive" : "badge--warning"}`}>
              <span className="badge__dot" />{connected ? "Connected" : "Not configured"}
            </span>
          }
          style={{ marginBottom: 14 }}
        >
          {settingsLoading ? (
            <div style={{ display: "grid", gap: 10 }}>
              {Array.from({ length: 3 }).map((_, i) => <Skel key={i} h={34} />)}
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {settings?.password_set && settings?.password_readable === false && (
                <div className="cx-note cx-note--bad" role="alert">
                  <div><b>Mail has stopped: the saved password can't be unlocked.</b> The project was moved or re-uploaded and
                    its encryption key changed. Type the Gmail <b>app password</b> below and press Save — nothing else needs to change.</div>
                </div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
                <Field label="Email account">
                  <input className="input" style={{ width: "100%" }} value={form.email_account}
                    onChange={(e) => set({ email_account: e.target.value })} placeholder="ops@company.com" autoComplete="off" />
                </Field>
                <Field label="From name">
                  <input className="input" style={{ width: "100%" }} value={form.from_name}
                    onChange={(e) => set({ from_name: e.target.value })} placeholder="Cortex Textile Limited" autoComplete="off" />
                </Field>
                <Field label="SMTP host">
                  <input className="input" style={{ width: "100%" }} value={form.smtp_host}
                    onChange={(e) => set({ smtp_host: e.target.value })} placeholder="smtp.gmail.com" autoComplete="off" />
                </Field>
                <Field label="SMTP port">
                  <input className="input" style={{ width: "100%" }} type="number" value={form.smtp_port}
                    onChange={(e) => set({ smtp_port: e.target.value })} placeholder="587" />
                </Field>
                <Field label={`Password${settings?.password_set ? (settings?.password_readable === false ? " (must be re-entered)" : " (saved)") : ""}`}>
                  <input className="input" style={{ width: "100%" }} type="password" value={form.password}
                    onChange={(e) => set({ password: e.target.value })}
                    placeholder={settings?.password_set && settings?.password_readable !== false ? "•••• (saved)" : "Gmail app password (16 letters)"}
                    autoComplete="new-password" />
                </Field>
              </div>

              <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5 }}>
                  <input type="checkbox" checked={form.use_tls} onChange={(e) => set({ use_tls: e.target.checked })} /> Use STARTTLS
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5 }}>
                  <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> Outbound email enabled
                </label>
              </div>

              {feedback && (
                <div style={{
                  display: "flex", gap: 8, alignItems: "center", padding: "9px 12px", borderRadius: "var(--radius-md)", fontSize: 12.5,
                  background: feedback.kind === "ok" ? "var(--positive-light)" : "var(--negative-light)",
                  color: feedback.kind === "ok" ? "var(--positive-ink)" : "var(--negative-ink)",
                }}>
                  {feedback.kind === "ok" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                  {feedback.text}
                </div>
              )}

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn btn--primary" disabled={saving} onClick={saveSettings}>
                  {saving ? <Loader2 size={13} className="spin" /> : <Save size={13} />} {saving ? "Saving…" : "Save settings"}
                </button>
                <button className="btn" disabled={testing} onClick={testSettings}>
                  {testing ? <Loader2 size={13} className="spin" /> : <FlaskConical size={13} />} {testing ? "Sending…" : "Send test email"}
                </button>
              </div>

              <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                The password is stored on the server and never returned to this page. Leave it blank to keep the saved one.
              </div>
            </div>
          )}
        </Card>
      )}

      <Card flush>
        {loading ? (
          <div style={{ padding: 18, display: "grid", gap: 10 }}>
            {Array.from({ length: 4 }).map((_, i) => <Skel key={i} h={72} r={10} />)}
          </div>
        ) : error ? (
          <Empty icon={<AlertTriangle size={18} />} title="Queue unavailable" hint={error} />
        ) : drafts.length === 0 ? (
          <Empty
            good={tab === "draft"}
            icon={<Inbox size={18} />}
            title={tab === "draft" ? "No drafts awaiting approval." : "Nothing here"}
            hint={tab === "draft" ? "Queue a grounded email from an action preview to review it here." : "No drafts match this filter."}
          />
        ) : (
          drafts.map((d) => {
            const st = STATUS_BADGE[d.status] || STATUS_BADGE.draft;
            const grounded = d.grounding_ok === true || d.grounding_ok === 1;
            const editing = editingId === d.id;
            const busy = busyId === d.id;
            return (
              <div key={d.id} className="row" style={{ alignItems: "flex-start" }}>
                <span className="row__rail" style={{ background: st.rail }} />

                <div className="row__main">
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span className={`badge ${st.cls}`}>{st.label}</span>
                    <span className={`badge ${grounded ? "badge--positive" : "badge--critical"}`}>
                      {grounded ? "Grounded" : "Blocked"}
                    </span>
                    {d.intent && (
                      <span className="badge badge--outline" style={{ textTransform: "capitalize" }}>
                        {String(d.intent).replace(/_/g, " ")}
                      </span>
                    )}
                    {d.created_at && (
                      <span style={{ fontSize: 11, color: "var(--text-muted)", display: "inline-flex", alignItems: "center", gap: 4 }}>
                        <Clock size={11} /> {fmtTime(d.created_at)}
                      </span>
                    )}
                  </div>

                  <div className="row__title" style={{ marginTop: 6 }}>{d.subject || "(no subject)"}</div>

                  <div className="row__meta" style={{ marginTop: 4 }}>
                    <span>To: <b>{d.to_email || "—"}</b></span>
                    {d.from_name && <span>From: <b>{d.from_name}</b></span>}
                    {d.policy_version && <span>{d.policy_version}</span>}
                    {d.decided_by && d.status !== "draft" && <span>By: <b>{d.decided_by}</b></span>}
                  </div>

                  {!editing && d.body && (
                    <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.6, color: "var(--text-secondary)", whiteSpace: "pre-wrap" }}>
                      {previewBody(d.body)}
                    </div>
                  )}

                  {editing && (
                    <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                      <Field label="To">
                        <input className="input" type="email" style={{ width: "100%" }} value={editTo}
                          onChange={(e) => { setEditTo(e.target.value); if (sendError?.id === d.id) setSendError(null); }}
                          placeholder="recipient@company.com" autoComplete="off" />
                      </Field>
                      <Field label="Subject">
                        <input className="input" style={{ width: "100%" }} value={editSubject}
                          onChange={(e) => setEditSubject(e.target.value)} placeholder="Subject" />
                      </Field>
                      <Field label="Body">
                        <textarea className="input" value={editBody} onChange={(e) => setEditBody(e.target.value)}
                          style={{ width: "100%", minHeight: 150, resize: "vertical", lineHeight: 1.6, whiteSpace: "pre-wrap" }} />
                      </Field>
                      {sendError?.id === d.id && (
                        <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "9px 12px", borderRadius: "var(--radius-md)", fontSize: 12.5, background: "var(--negative-light)", color: "var(--negative-ink)" }}>
                          <AlertTriangle size={14} /> {sendError.text}
                        </div>
                      )}
                      <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                        Edited messages are re-checked against the live records before they are sent.
                      </div>
                    </div>
                  )}

                  {d.status === "sent" && d.message_id && (
                    <div style={{ marginTop: 6, fontSize: 11.5, color: "var(--text-muted)", wordBreak: "break-all" }}>
                      Message-ID: {d.message_id}
                    </div>
                  )}
                  {d.status === "failed" && d.error && (
                    <div style={{ marginTop: 6, fontSize: 11.5, color: "var(--negative-ink)" }}>{d.error}</div>
                  )}
                </div>

                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end", maxWidth: 280 }}>
                  {d.status === "draft" && !editing && (
                    <>
                      <button className="btn btn--sm btn--positive" disabled={busy} onClick={() => approve(d)}>
                        {busy ? <Loader2 size={12} className="spin" /> : <Send size={12} />} Approve &amp; Send
                      </button>
                      <button className="btn btn--sm" disabled={busy} onClick={() => startEdit(d)}>
                        <Pencil size={12} /> Edit
                      </button>
                      <button className="btn btn--sm btn--danger" disabled={busy} onClick={() => reject(d)}>
                        <X size={12} /> Reject
                      </button>
                    </>
                  )}

                  {editing && (
                    <>
                      <button className="btn btn--sm btn--positive" disabled={busy}
                        onClick={() => approve(d, { subject: editSubject, body: editBody, to_email: editTo })}>
                        {busy ? <Loader2 size={12} className="spin" /> : <Send size={12} />} Save &amp; Send
                      </button>
                      <button className="btn btn--sm" disabled={busy} onClick={() => setEditingId(null)}>Cancel</button>
                    </>
                  )}

                  {(d.status === "rejected" || d.status === "failed") && (
                    <button className="btn btn--sm btn--ghost" disabled={busy} onClick={() => remove(d)} title="Delete draft">
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </Card>

      <div style={{ marginTop: 12, fontSize: 11.5, color: "var(--text-muted)" }}>
        Emails are sent only after you approve them. Approving sends the grounded message through the
        configured SMTP account and records the decision in the audit log.
      </div>
    </>
  );
}
