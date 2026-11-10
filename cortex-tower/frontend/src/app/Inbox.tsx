import { useEffect, useState } from "react";
import { Archive, ArchiveRestore, ArrowLeft, Briefcase, ChevronDown, ChevronRight, Paperclip, RefreshCw, Reply, Search, Send, Sparkles } from "lucide-react";
import { Badge, Btn, Empty, LABEL_TONE, Loading, Note, Select, StageBadge, Textarea, call, openAttachment, useCall, useToast, when } from "./kit";
import type { R } from "./kit";
import { CustomerPicker } from "./CustomerPicker";

const FOLDERS = [
  { v: "all", l: "All" }, { v: "needs_reply", l: "Needs reply" }, { v: "inquiry", l: "Inquiries" }, { v: "orders", l: "Orders" },
  { v: "money", l: "Invoices & payments" }, { v: "questions", l: "Questions" }, { v: "other", l: "Other" }, { v: "archived", l: "Archived" }, { v: "system", l: "System" },
];
const LABELS = [
  { v: "inquiry", l: "Inquiry" }, { v: "new_order", l: "Order" }, { v: "order_amendment", l: "Amendment" }, { v: "invoice", l: "Invoice" },
  { v: "remittance", l: "Payment" }, { v: "query", l: "Question" }, { v: "other", l: "Other" },
];

export function Inbox({ go, threadKey, onCounts }: { go: (path: string) => void; threadKey?: string; onCounts?: (c: R) => void }) {
  const toast = useToast();
  const [folder, setFolder] = useState<string>(() => { try { return localStorage.getItem("ws_folder") || "all"; } catch { return "all"; } });
  const [q, setQ] = useState("");
  const [qLive, setQLive] = useState("");
  const [syncing, setSyncing] = useState(false);
  const list = useCall("inbox_threads", { folder, q: qLive, limit: 200 }, []);
  useEffect(() => { const t = window.setTimeout(() => setQLive(q), 250); return () => window.clearTimeout(t); }, [q]);
  useEffect(() => { try { localStorage.setItem("ws_folder", folder); } catch { /* private */ } }, [folder]);
  useEffect(() => { if (list.data?.counts && onCounts) onCounts(list.data.counts); }, [list.data, onCounts]);

  const sync = async (quiet = false) => {
    setSyncing(true);
    const r = await call("inbox_sync");
    setSyncing(false);
    if (!r.ok) { if (!quiet) toast(r.error || "The mailbox did not answer.", "bad"); return; }
    if (!quiet) toast(r.fetched ? `${r.fetched} new mail${r.fetched > 1 ? "s" : ""}${r.deal_replies ? ` · ${r.deal_replies} deal${r.deal_replies > 1 ? "s" : ""} got a reply` : ""}` : "No new mail.");
    void list.reload(true);
  };
  /* read the mailbox when the inbox opens, then every 2 minutes while it is visible */
  useEffect(() => {
    void sync(true);
    const t = window.setInterval(() => { if (document.visibilityState === "visible") void sync(true); }, 120000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const threads: R[] = list.data?.threads || [];
  const counts: R = list.data?.counts || {};
  return (
    <div className={`ws-inbox${threadKey ? " has-thread" : ""}`}>
      <div className="ws-inbox__list">
        <div className="ws-inbox__tools">
          <div className="ws-row">
            <div style={{ position: "relative", flex: 1 }}>
              <Search size={14} style={{ position: "absolute", left: 10, top: 10, color: "var(--ws-faint)" }} />
              <input className="ws-input" style={{ paddingLeft: 30 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search mail" aria-label="Search mail" />
            </div>
            <Btn icon title="Check for new mail" onClick={() => sync()} busy={syncing}>{!syncing && <RefreshCw size={15} />}</Btn>
          </div>
          <div className="ws-chips">
            {FOLDERS.map((f) => {
              const n = counts[f.v];
              return <button key={f.v} className={`ws-chip${folder === f.v ? " is-on" : ""}`} onClick={() => setFolder(f.v)}>{f.l}{n ? <span className="n">{n}</span> : null}</button>;
            })}
          </div>
        </div>
        <div className="ws-inbox__scroll">
          {list.loading && !list.data ? <div style={{ padding: 14 }}><Loading rows={6} /></div>
            : list.error ? <div style={{ padding: 14 }}><Note tone="bad">{list.error}</Note></div>
            : threads.length === 0 ? <Empty title={folder === "needs_reply" ? "Nothing waiting for a reply" : "No conversations here"} text={q ? "Try another search." : "New mail appears here as soon as it arrives."} />
            : threads.map((t) => (
              <button key={t.key} className={`ws-thread-row${t.key === threadKey ? " is-on" : ""}${t.unread ? " is-unread" : ""}`} onClick={() => go(`inbox/${encodeURIComponent(t.key)}`)}>
                <div className="ws-thread-row__top">
                  <span className="ws-thread-row__from">{t.from_name || t.from_addr || "(unknown sender)"}</span>
                  {t.count > 1 && <span className="ws-small ws-muted">{t.count}</span>}
                  <span className="ws-thread-row__at">{when(t.last_at)}</span>
                </div>
                <div className="ws-thread-row__subj">{t.subject}</div>
                <div className="ws-thread-row__snip">{t.last_from === "us" ? "You: " : ""}{t.snippet}</div>
                <div className="ws-thread-row__tags">
                  <Badge tone={LABEL_TONE[t.label]}>{t.label_name}</Badge>
                  {t.needs_reply && <Badge tone="bad">Needs reply</Badge>}
                  {t.deal && <StageBadge stage={t.deal.stage} label={`Deal · ${t.deal.stage}`} />}
                  {t.attachments > 0 && <span className="ws-small ws-muted"><Paperclip size={12} style={{ verticalAlign: -2 }} /> {t.attachments}</span>}
                </div>
              </button>
            ))}
        </div>
      </div>
      <div className="ws-inbox__view">
        {threadKey ? <Thread key={threadKey} threadKey={threadKey} go={go} onChanged={() => list.reload(true)} />
          : <div className="ws-conv" style={{ display: "grid", placeItems: "center" }}><Empty title="Pick a conversation" text="Inquiries, orders and replies from buyers, as one thread each." /></div>}
      </div>
    </div>
  );
}

function Message({ m, open, toggle, toast }: { m: R; open: boolean; toggle: () => void; toast: (s: string, t?: "ok" | "bad") => void }) {
  const [quoted, setQuoted] = useState(false);
  const hasQuoted = (m.body || "").trim().length > (m.fresh || "").trim().length + 20;
  return (
    <div className={`ws-msg${m.direction === "out" ? " is-out" : ""}`}>
      <div className="ws-msg__head" onClick={toggle}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="ws-msg__who">{m.direction === "out" ? "You" : m.from_name || m.from_addr}{m.direction !== "out" && m.from_name ? <span className="ws-msg__meta"> &lt;{m.from_addr}&gt;</span> : null}</div>
          <div className="ws-msg__meta ws-ellipsis">{m.direction === "out" ? `to ${m.to}` : `to ${m.to || "us"}`}{m.cc ? ` · cc ${m.cc}` : ""}</div>
        </div>
        {m.label && m.label !== "other" && m.direction !== "out" && <Badge tone={LABEL_TONE[m.label]}>{m.label_name}</Badge>}
        <span className="ws-msg__meta ws-nowrap">{when(m.at)}</span>
      </div>
      {open && <>
        <div className="ws-msg__body">{m.fresh || m.body || <span className="ws-muted">(no text)</span>}
          {hasQuoted && <div className="ws-mt-s"><Btn kind="plain" sm onClick={() => setQuoted(!quoted)}>{quoted ? "Hide" : "Show"} earlier messages</Btn></div>}
          {quoted && <div className="ws-msg__quoted">{(m.body || "").slice((m.fresh || "").length)}</div>}
        </div>
        {m.attachments?.length > 0 && <div className="ws-atts">{m.attachments.map((a: R) => (
          <button key={a.id} className="ws-att" onClick={() => openAttachment(a.id, toast)} title={a.filename}><Paperclip size={13} /><span className="ws-ellipsis">{a.filename}</span></button>))}</div>}
      </>}
    </div>
  );
}

function Thread({ threadKey, go, onChanged }: { threadKey: string; go: (p: string) => void; onChanged: () => void }) {
  const toast = useToast();
  const t = useCall("inbox_thread", { key: threadKey });
  const [openIds, setOpenIds] = useState<Record<string, boolean>>({});
  const [body, setBody] = useState("");
  const [cc, setCc] = useState("");
  const [showCc, setShowCc] = useState(false);
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);
  const [composer, setComposer] = useState(false);
  const d = t.data || {};
  const msgs: R[] = d.messages || [];
  useEffect(() => { if (msgs.length) setOpenIds({ [`${msgs[msgs.length - 1].kind}${msgs[msgs.length - 1].id}`]: true }); }, [msgs.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const draftKey = `ws_draft:${threadKey}`;
  useEffect(() => { try { setBody(localStorage.getItem(draftKey) || ""); } catch { /* */ } }, [draftKey]);
  useEffect(() => { try { if (body) localStorage.setItem(draftKey, body); else localStorage.removeItem(draftKey); } catch { /* */ } }, [body, draftKey]);

  if (t.loading && !t.data) return <div style={{ padding: 20 }}><Loading rows={4} /></div>;
  if (t.error) return <div style={{ padding: 20 }}><Note tone="bad">{t.error}</Note></div>;

  const send = async () => {
    setSending(true);
    const r = await call("inbox_reply", { key: threadKey, body, cc });
    setSending(false);
    if (!r.ok) { toast(r.error || "Not sent.", "bad"); return; }
    toast(`Sent to ${r.to} in this conversation.`);
    setBody(""); setComposer(false);
    await t.reload(true); onChanged();
  };
  const startDeal = async () => {
    setStarting(true);
    const r = await call("deal_from_thread", { key: threadKey });
    setStarting(false);
    if (!r.ok) { toast(r.error || "Could not start the deal.", "bad"); return; }
    toast(`Deal started: ${r.deal.styles.length} style(s) read from the mail.`);
    onChanged();
    go(`deals/${r.deal.id}`);
  };
  const relabel = async (label: string) => {
    const r = await call("inbox_label", { key: threadKey, label });
    if (r.ok) { toast("Label updated."); await t.reload(true); onChanged(); } else toast(r.error || "Not changed.", "bad");
  };
  const archive = async (on: boolean) => {
    const r = await call("inbox_archive", { key: threadKey, archived: on });
    if (r.ok) { toast(on ? "Archived." : "Back in the inbox."); onChanged(); if (on) go("inbox"); } else toast(r.error || "Not changed.", "bad");
  };
  const archived = !!d.archived;
  const deal = d.deal;
  const match = d.customer_match || {};
  const lastIn = [...msgs].reverse().find((m) => m.direction === "in");

  return (
    <>
      <div className="ws-conv">
        <div className="ws-conv__head">
          <div className="ws-row" style={{ marginBottom: 4 }}>
            <Btn kind="plain" sm onClick={() => go("inbox")}><ArrowLeft size={14} /> Inbox</Btn>
            <Badge tone={LABEL_TONE[d.label]}>{d.label_name}</Badge>
            {deal && <StageBadge stage={deal.stage} label={deal.stage_label} />}
            <span style={{ marginLeft: "auto" }} />
            <Btn sm icon title="Archive" onClick={() => archive(!archived)}>{archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}</Btn>
          </div>
          <h2>{d.subject}</h2>
          <div className="ws-small ws-muted">{d.party?.name ? `${d.party.name} · ` : ""}{d.party?.email} · {msgs.length} message{msgs.length === 1 ? "" : "s"}</div>
        </div>
        <div className="ws-conv__scroll">
          {msgs.map((m) => {
            const k = `${m.kind}${m.id}`;
            return <Message key={k} m={m} open={!!openIds[k]} toggle={() => setOpenIds((o) => ({ ...o, [k]: !o[k] }))} toast={toast} />;
          })}
        </div>
        <div className="ws-composer">
          {!composer ? (
            <div className="ws-row">
              <Btn kind="primary" onClick={() => setComposer(true)}><Reply size={14} /> Reply in this thread</Btn>
              {body && <span className="ws-small ws-muted">Draft saved</span>}
            </div>
          ) : (<>
            <div className="ws-row ws-small ws-muted">
              <span>To <b style={{ color: "var(--ws-text)" }}>{lastIn?.from_addr || d.party?.email}</b> · subject “Re: {d.subject}” · stays in this conversation</span>
              <Btn kind="plain" sm onClick={() => setShowCc(!showCc)}>Cc</Btn>
            </div>
            {showCc && <input className="ws-input" value={cc} onChange={(e) => setCc(e.target.value)} placeholder="cc@example.com" aria-label="Cc" />}
            <Textarea value={body} onChange={setBody} rows={6} placeholder="Write your reply…" />
            <div className="ws-row">
              <Btn kind="primary" busy={sending} disabled={!body.trim()} onClick={send}><Send size={14} /> Send</Btn>
              <Btn kind="ghost" onClick={() => setComposer(false)}>Close</Btn>
            </div>
          </>)}
        </div>
      </div>
      <aside className="ws-aside">
        {deal ? (
          <div>
            <h4>Deal</h4>
            <div className="ws-card" style={{ padding: 12 }}>
              <b style={{ display: "block" }}>{deal.title}</b>
              <div className="ws-row ws-mt-s"><StageBadge stage={deal.stage} label={deal.stage_label} /><span className="ws-small ws-muted">{deal.customer_name || "No customer yet"}</span></div>
              {deal.attention?.kind === "buyer_replied" && <div className="ws-mt-s"><Note tone="warn">{deal.attention.text}</Note></div>}
              <div className="ws-mt"><Btn kind="dark" onClick={() => go(`deals/${deal.id}`)}><Briefcase size={14} /> Open the deal</Btn></div>
            </div>
          </div>
        ) : (
          <div>
            <h4>Start work</h4>
            <div className="ws-card" style={{ padding: 12, display: "grid", gap: 10 }}>
              {d.label === "inquiry"
                ? <div className="ws-small">The buyer is asking for a price. Start a deal: the styles, quantities and BOM are read from this mail. No price is needed yet.</div>
                : <div className="ws-small ws-muted">Turn this conversation into a deal if the buyer is asking for a price.</div>}
              <Btn kind="primary" busy={starting} onClick={startDeal}><Sparkles size={14} /> Start a deal from this mail</Btn>
              {(d.label === "new_order" || d.label === "order_amendment") && <Btn kind="ghost" onClick={() => go("more/intake")}>Open in Order intake</Btn>}
            </div>
          </div>
        )}
        {!deal && (
          <div>
            <h4>Customer</h4>
            {match.customer ? <div className="ws-card ws-small" style={{ padding: 12 }}>Recognised as <b>{match.customer_name || match.customer}</b> ({match.how}).</div>
              : <CustomerPicker compact email={d.party?.email} contactName={d.party?.name} onPicked={async (c) => {
                const r = await call("inbox_link_customer", { key: threadKey, customer: c });
                toast(r.ok ? `Linked to ${c}. Deals from this buyer use it.` : r.error || "Not linked.", r.ok ? "ok" : "bad");
                void t.reload(true);
              }} />}
          </div>
        )}
        <div>
          <h4>Label</h4>
          <Select value={d.label} onChange={relabel} options={LABELS} />
          <div className="ws-small ws-muted ws-mt-s">Wrong label? Change it; the correction sticks.</div>
        </div>
        {lastIn && lastIn.reasons?.length > 0 && <div><h4>Why this label</h4><div className="ws-small ws-muted">{lastIn.reasons.join(" · ")}</div></div>}
      </aside>
    </>
  );
}
