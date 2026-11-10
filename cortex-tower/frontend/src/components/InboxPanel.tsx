import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ClipboardList,
  ExternalLink,
  FileText,
  Inbox,
  Loader2,
  Mail,
  MailOpen,
  RefreshCw,
  RotateCcw,
  ScanLine,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import { callInbox } from "../services/api";
import { Card, Drawer, Empty, Skel } from "../ui";
import { IntakeReview } from "./IntakeReview";
import { CLASS_BADGE, CLASS_LABEL, fmtTime } from "../types";
import type { InboxSummary, MailMessage, OrderChange } from "../types";

type Tab = "attention" | "inbox" | "decided";

const SEV_RAIL: Record<string, string> = {
  critical: "var(--negative)",
  warning: "var(--warning)",
  info: "var(--border-strong)",
};

function conf(score?: number): { cls: string; label: string } {
  const n = Number(score || 0);
  if (n >= 80) return { cls: "badge--positive", label: `${n}%` };
  if (n >= 60) return { cls: "badge--warning", label: `${n}%` };
  return { cls: "badge--outline", label: `${n}%` };
}

/* ── Inbound mail — understood inbox + order-change queue ─────────────────── */
/** Set once per browser session: the mailbox is read when a screen opens. */
let _autoSynced = false;

export function InboxPanel({ notify, onOpenIntake }: {
  notify: (msg: string, opts?: { sticky?: boolean; link?: { url: string; label: string } }) => void;
  onOpenIntake?: (runId?: number) => void;
}) {
  const [tab, setTab] = useState<Tab>("attention");
  const [summary, setSummary] = useState<InboxSummary | null>(null);
  const [changes, setChanges] = useState<OrderChange[]>([]);
  const [decided, setDecided] = useState<OrderChange[]>([]);
  const [messages, setMessages] = useState<MailMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  // Nothing runs on a clock in this app, so the screen says WHEN it last reached the
  // mailbox, and it reaches it once when opened — not on a timer (2026-11-04, D-126).
  const [freshness, setFreshness] = useState<string>("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [detail, setDetail] = useState<MailMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  /* one document = one decision card, keyed by the mail it came from */
  const [runs, setRuns] = useState<Record<number, any>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, pend, dec, inbox, iq] = await Promise.all([
        callInbox("get_inbox_summary"),
        callInbox("get_order_changes", { status: "pending" }),
        callInbox("get_order_changes", { status: "all" }),
        callInbox("get_inbox"),
        callInbox("get_intake_queue", { limit: 200 }),
      ]);
      if (iq.success && iq.data) {
        const map: Record<number, any> = {};
        (iq.data.items || []).forEach((r: any) => { if (r.mail_id) map[r.mail_id] = r; });
        setRuns(map);
      }
      if (s.success && s.data) setSummary(s.data as InboxSummary);
      setChanges(pend.success && pend.data?.changes ? pend.data.changes : []);
      setDecided(
        (dec.success && dec.data?.changes ? dec.data.changes : []).filter(
          (c: OrderChange) => c.status !== "pending"
        )
      );
      setMessages(inbox.success && inbox.data?.messages ? inbox.data.messages : []);
      setFreshness(inbox.data?.freshness?.mail?.ago || "");
    } catch {
      setError("Could not reach the KOGO middleware.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    // read the mailbox when the screen opens, once per browser session (no scheduler)
    if (!_autoSynced) {
      _autoSynced = true;
      callInbox("sync_inbox", { limit: 25, notify: 0 })
        .then(() => load())
        .catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  const sync = async () => {
    setSyncing(true);
    try {
      const res = await callInbox("sync_inbox", { limit: 25, notify: 1 });
      if (res.success && res.data) {
        const d = res.data;
        if (d.ok === false) {
          notify("Mailbox not connected — check Mail Settings on the Outbound Mail page.");
        } else {
          notify(
            d.fetched === 0
              ? "Inbox already up to date."
              : `Read ${d.fetched} new mail — ${d.flagged} item(s) need attention.`
          );
        }
        await load();
      } else {
        notify("Could not sync the inbox.");
      }
    } catch {
      notify("Could not reach the mailbox.");
    } finally {
      setSyncing(false);
    }
  };

  const decide = async (ch: OrderChange, decision: "approve" | "dismiss") => {
    setBusyId(ch.id);
    try {
      const res = await callInbox("decide_order_change", { change_id: ch.id, decision });
      if (res.success && res.data?.ok !== false) {
        const chg = res.data?.change;
        const note = chg?.result_note;
        const erpUrl = chg?.erp_url || chg?.erp_list_url;
        const erpLabel = chg?.erp_doctype ? `Open ${chg.erp_doctype} in ERP` : "Open in ERP";
        if (decision === "approve" && chg?.needs_action) {
          // Not finished — keep it loud and on screen until it is.
          notify(
            `Still open — ${note} Use “Open in ERP to complete”, then approve again.`,
            { sticky: true, link: erpUrl ? { url: erpUrl, label: "Open in ERP to complete" } : undefined }
          );
        } else if (decision === "approve") {
          // Done — hand the user straight to the record that was created.
          notify(
            `Approved: ${ch.title.slice(0, 60)}${note ? ` — ${note}` : ""}`,
            { sticky: true, link: erpUrl ? { url: erpUrl, label: erpLabel } : undefined }
          );
          setTab("decided");          // show the card + its Open-in-ERP button
        } else {
          notify(`Dismissed: ${ch.title.slice(0, 60)}`);
        }
        await load();
      } else {
        notify(res.data?.error || "Could not record the decision.", { sticky: true });
      }
    } finally {
      setBusyId(null);
    }
  };

  const rollback = async (ch: OrderChange) => {
    setBusyId(ch.id);
    try {
      const res = await callInbox("rollback_order_change", { change_id: ch.id });
      if (res.success && res.data?.ok !== false) {
        notify(res.data?.note || "Rolled back — the item is back in the queue.", { sticky: true });
        await load();
      } else {
        notify(res.data?.error || "Could not roll this back.", { sticky: true });
      }
    } finally {
      setBusyId(null);
    }
  };

  const openMail = async (m: MailMessage) => {
    const res = await callInbox("get_mail_message", { mail_id: m.id });
    setDetail(res.success && res.data?.message ? (res.data.message as MailMessage) : m);
  };

  const cards = tab === "attention" ? changes : tab === "decided" ? decided : [];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* header strip */}
      <Card
        title="Inbox — read and understood"
        sub={
          summary
            ? `${summary.total_mail} message(s) read · ${summary.pending_changes} awaiting your decision`
              + (freshness ? ` · synced ${freshness}` : " · never synced")
            : "Mailbox not synced yet"
        }
        actions={
          <button className="btn btn--primary btn--sm" onClick={sync} disabled={syncing}>
            {syncing ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />}
            {syncing ? "Reading inbox…" : "Sync inbox"}
          </button>
        }
      >
        {loading ? (
          <Skel h={40} />
        ) : (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            {summary?.critical ? (
              <span className="badge badge--critical"><span className="badge__dot" />{summary.critical} critical</span>
            ) : null}
            {(summary?.by_classification || []).map((c) => (
              <span key={c.key} className={`badge ${CLASS_BADGE[c.key] || "badge--outline"}`}>
                {c.label}: {c.count}
              </span>
            ))}
            {!summary?.total_mail && (
              <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                No mail read yet — press <b>Sync inbox</b> to read the mailbox.
              </span>
            )}
          </div>
        )}
      </Card>

      {/* tabs */}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {([
          { id: "attention", label: `Needs your decision${changes.length ? ` (${changes.length})` : ""}` },
          { id: "inbox", label: `All mail${messages.length ? ` (${messages.length})` : ""}` },
          { id: "decided", label: "Decided" },
        ] as { id: Tab; label: string }[]).map((t) => (
          <button
            key={t.id}
            className={`btn btn--sm${tab === t.id ? " btn--brand" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
        <button className="btn btn--sm btn--ghost" style={{ marginLeft: "auto" }} onClick={load} disabled={loading}>
          <RefreshCw size={12} className={loading ? "spin" : undefined} /> Refresh
        </button>
      </div>

      {error && (
        <div className="banner banner--warning">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* the decisions live on the intake screen — say so, and make it one click */}
      <div className="banner" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
                                       background: "var(--primary-light)", border: "1px solid var(--border)" }}>
        <ScanLine size={15} />
        <span style={{ fontSize: 12.5 }}>
          This is the <b>raw mailbox</b>. The document-level decision — what the PO says, what will be
          created, approve or reject — lives in <b>Order intake</b>.
        </span>
        <button className="btn btn--sm btn--brand" style={{ marginLeft: "auto" }} onClick={() => onOpenIntake?.()}>
          Open Order intake
        </button>
      </div>

      {/* needs-decision / decided cards */}
      {tab !== "inbox" && (
        <>
          {loading ? (
            <Skel h={120} r={12} />
          ) : cards.length === 0 ? (
            <Card>
              <Empty
                icon={<ClipboardList size={18} />}
                good={tab === "attention"}
                title={tab === "attention" ? "Nothing is waiting on you" : "No decisions recorded yet"}
                hint={tab === "attention" ? "New orders and amendments will appear here after a sync." : undefined}
              />
            </Card>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {cards.map((c) => (
                <div key={c.id} className="card" style={{ borderLeft: `3px solid ${SEV_RAIL[c.severity] || "var(--border-strong)"}` }}>
                  <div className="card__body" style={{ display: "grid", gap: 8 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span className={`badge ${CLASS_BADGE[c.change_type] || "badge--outline"}`}>
                        {CLASS_LABEL[c.change_type] || c.change_type}
                      </span>
                      {c.severity === "critical" && <span className="badge badge--critical">Act now</span>}
                      {c.status !== "pending" && (
                        <span className="badge badge--outline">{c.status}</span>
                      )}
                      <span style={{ marginLeft: "auto", fontSize: 11.5, color: "var(--text-muted)" }}>
                        {fmtTime(c.created_at || "")}
                      </span>
                    </div>

                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{c.title}</div>
                    {c.summary && <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>{c.summary}</div>}

                    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12, color: "var(--text-muted)" }}>
                      {c.so_name && <span>Order <b style={{ color: "var(--text-secondary)" }}>{c.so_name}</b></span>}
                      {c.po_no && <span>PO <b style={{ color: "var(--text-secondary)" }}>{c.po_no}</b></span>}
                      {c.customer && <span>Customer <b style={{ color: "var(--text-secondary)" }}>{c.customer}</b></span>}
                    </div>

                    {c.mail_id && runs[c.mail_id] && (
                      <IntakeActions run={runs[c.mail_id]} notify={notify} compact
                                     onOpen={() => onOpenIntake?.(runs[c.mail_id!].id)}
                                     onDone={load} />
                    )}

                    {(c.next_steps || []).length > 0 && !(c.mail_id && runs[c.mail_id]) && (
                      <div style={{ background: "var(--surface-sunken)", borderRadius: 8, padding: "8px 10px" }}>
                        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 4 }}>
                          Next steps
                        </div>
                        <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: "var(--text-secondary)", display: "grid", gap: 2 }}>
                          {(c.next_steps || []).map((s, i) => <li key={i}>{s}</li>)}
                        </ul>
                      </div>
                    )}

                    {c.result_note && !c.needs_action && (
                      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{c.result_note}</div>
                    )}

                    {c.needs_action && (
                      <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 12px",
                                    background: "var(--warning-light)", border: "1px solid #fcd34d",
                                    borderRadius: 8, fontSize: 12.5, color: "var(--warning-ink)" }}>
                        <AlertTriangle size={14} style={{ flex: "0 0 14px", marginTop: 2 }} />
                        <div style={{ flex: 1 }}>
                          <b>Action needed in the ERP</b> — this item stays in the queue until it is finished.
                          {c.result_note && <div style={{ marginTop: 3 }}>{c.result_note}</div>}
                          {(c.erp_url || c.erp_list_url) && (
                            <a className="btn btn--sm" style={{ marginTop: 8 }}
                               href={(c.erp_url || c.erp_list_url) as string} target="_blank" rel="noreferrer">
                              <ExternalLink size={12} /> Open in ERP to complete
                            </a>
                          )}
                        </div>
                      </div>
                    )}

                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      {c.mail_id && (
                        <button
                          className="btn btn--sm btn--ghost"
                          onClick={() => {
                            const m = messages.find((x) => x.id === c.mail_id);
                            if (m) openMail(m);
                          }}
                        >
                          <Mail size={12} /> View email
                        </button>
                      )}
                      {(c.erp_url || c.erp_list_url) && (
                        <a
                          className="btn btn--sm"
                          href={(c.erp_url || c.erp_list_url) as string}
                          target="_blank"
                          rel="noreferrer"
                          title={`Open ${c.erp_doctype || "this record"} in KOGO ERP`}
                        >
                          <ExternalLink size={12} /> Open in ERP
                        </a>
                      )}
                      {c.status === "approved" && (
                        <button className="btn btn--sm btn--ghost" onClick={() => rollback(c)}
                                disabled={busyId === c.id}
                                title="Undo: delete everything this created in the ERP and put the item back in the queue">
                          {busyId === c.id ? <Loader2 size={12} className="spin" /> : <RotateCcw size={12} />} Roll back
                        </button>
                      )}
                      {c.status === "pending" && (
                        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                          <button className="btn btn--sm" onClick={() => decide(c, "dismiss")} disabled={busyId === c.id}>
                            <ThumbsDown size={12} /> Dismiss
                          </button>
                          <button className="btn btn--sm btn--positive" onClick={() => decide(c, "approve")} disabled={busyId === c.id}>
                            {busyId === c.id ? <Loader2 size={12} className="spin" /> : <ThumbsUp size={12} />} Approve
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* all mail list */}
      {tab === "inbox" && (
        <Card flush>
          {loading ? (
            <div className="card__body"><Skel h={120} /></div>
          ) : messages.length === 0 ? (
            <Empty icon={<Inbox size={18} />} title="No mail read yet" hint="Press Sync inbox to read the mailbox." />
          ) : (
            <div>
              {messages.map((m) => {
                const cb = CLASS_BADGE[m.classification] || "badge--outline";
                const c = conf(m.confidence);
                return (
                  <button
                    key={m.id}
                    onClick={() => openMail(m)}
                    style={{
                      display: "grid", gridTemplateColumns: "1fr auto", gap: 10, width: "100%",
                      textAlign: "left", padding: "12px 18px", border: 0, borderBottom: "1px solid var(--border)",
                      background: m.status === "new" ? "var(--primary-light)" : "transparent", cursor: "pointer",
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <span className={`badge ${cb}`}>{CLASS_LABEL[m.classification] || m.classification}</span>
                        <span className={`badge ${c.cls}`}>{c.label}</span>
                        {!!m.has_attachments && <span className="badge badge--outline"><FileText size={10} /> attachment</span>}
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {m.subject || "(no subject)"}
                      </div>
                      <div style={{ fontSize: 12, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {m.from_name || m.from_addr} · {m.snippet}
                      </div>
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{fmtTime(m.received_at || "")}</div>
                  </button>
                );
              })}
            </div>
          )}
        </Card>
      )}

      {/* mail detail */}
      {detail && (
        <Drawer
          onClose={() => setDetail(null)}
          title={detail.subject || "(no subject)"}
          sub={`${detail.from_name || ""} <${detail.from_addr || ""}> · ${fmtTime(detail.received_at || "")}`}
          footer={<button className="btn btn--sm" onClick={() => setDetail(null)}><X size={12} /> Close</button>}
        >
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
            <span className={`badge ${CLASS_BADGE[detail.classification] || "badge--outline"}`}>
              {CLASS_LABEL[detail.classification] || detail.classification}
            </span>
            <span className={`badge ${conf(detail.confidence).cls}`}>confidence {detail.confidence || 0}%</span>
            {(detail.po_refs || []).map((p) => <span key={p} className="badge badge--brand">PO {p}</span>)}
            {(detail.matched_orders || []).map((o) => (
              <span key={o.so} className="badge badge--positive">{o.so}{o.po_no ? ` · PO ${o.po_no}` : ""}</span>
            ))}
          </div>

          {runs[detail.id] && <IntakeActions run={runs[detail.id]} notify={notify}
                                             onOpen={() => onOpenIntake?.(runs[detail.id].id)}
                                             onDone={load} />}

          {(detail.attachments || []).length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 6 }}>
                Attachments {runs[detail.id] ? "(opened and read)" : "(names only)"}
              </div>
              <div style={{ display: "grid", gap: 4 }}>
                {(detail.attachments || []).map((a, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5 }}>
                    <FileText size={12} /> {a.filename}
                    <span style={{ color: "var(--text-muted)" }}>{a.size ? `${Math.round((a.size || 0) / 1024)} KB` : ""}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 6 }}>
            Why it was classified this way
          </div>
          <ul style={{ margin: "0 0 14px", paddingLeft: 16, fontSize: 12.5, color: "var(--text-secondary)", display: "grid", gap: 2 }}>
            {(detail.reasons || []).map((r, i) => <li key={i}>{r}</li>)}
          </ul>

          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 6 }}>
            <MailOpen size={12} /> Message
          </div>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 12.5, color: "var(--text-secondary)", margin: 0, background: "var(--surface-sunken)", padding: 12, borderRadius: 8 }}>
            {detail.body_text || detail.snippet || "(no text body)"}
          </pre>
        </Drawer>
      )}
    </div>
  );
}


/* ── The decision, right where the operator already is ─────────────────────
   The intake card is the place that shows everything, but a mail opened from
   the inbox must not dead-end: the same approve / simulate / reject is here. */
function IntakeActions({ run, notify, onOpen, onDone, compact }: {
  run: any; notify: (m: string, o?: any) => void; onOpen: () => void; onDone: () => void; compact?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const act = async (name: string, params: Record<string, any>, label: string) => {
    setBusy(name);
    try {
      const r = await callInbox(name, params);
      const d = r.data || {};
      if (d.ok === false) notify(`${label} failed: ${d.error || d.note || "unknown"}`, { sticky: true });
      else notify(d.note ? `${label}: ${d.note}` : `${label} done`, { sticky: !!d.note });
      onDone();
    } finally { setBusy(null); }
  };
  const blocked = (run.blocking || []).length;
  const badge = run.status === "approved" ? "badge--positive"
    : run.status === "rejected" ? "badge--outline"
    : run.status === "simulated" ? "badge--warning" : "badge--info";
  return (
    <div className="intake-inbox" style={{ marginBottom: compact ? 0 : 14, border: "1px solid var(--border)",
                                          borderRadius: 10, padding: 12, background: "var(--surface-hover)" }}>
      {reviewing && <IntakeReview runId={run.id} onClose={() => setReviewing(false)}
        onDone={(msg) => { setReviewing(false); notify(msg, { sticky: true }); onDone(); }} />}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <ScanLine size={13} />
        <b style={{ fontSize: 12.5 }}>Order intake #{run.id} — the document was read</b>
        <span className={`badge ${badge}`}>{run.status}</span>
        <span className="badge badge--outline">{run.route}</span>
        {blocked > 0 && <span className="badge badge--warning">{blocked} blocked</span>}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10 }}>{run.summary || "—"}</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {run.status !== "approved" && run.status !== "rejected" && (
          <button className="btn btn--sm btn--primary" onClick={() => setReviewing(true)} disabled={!!busy}
                  title="See and change every value first; nothing is written until you confirm">
            <ThumbsUp size={12} /> Review &amp; approve
          </button>
        )}
        <button className="btn btn--sm" onClick={() => act("simulate_intake", { run_id: run.id }, "Simulate")} disabled={!!busy}>
          {busy === "simulate_intake" ? <Loader2 size={12} className="spin" /> : <ClipboardList size={12} />} Simulate
        </button>
        {run.status !== "approved" && run.status !== "rejected" && (
          <button className="btn btn--sm" onClick={() => act("reject_intake", { run_id: run.id, reason: "not an order" }, "Reject")} disabled={!!busy}>
            <ThumbsDown size={12} /> Reject
          </button>
        )}
        {run.status === "approved" && (
          <button className="btn btn--sm" onClick={() => act("rollback_intake", { run_id: run.id }, "Rollback")} disabled={!!busy}>
            <RotateCcw size={12} /> Roll back
          </button>
        )}
        <button className="btn btn--sm btn--ghost" style={{ marginLeft: "auto" }} onClick={onOpen}>
          <ExternalLink size={12} /> Open the full card
        </button>
      </div>
    </div>
  );
}
