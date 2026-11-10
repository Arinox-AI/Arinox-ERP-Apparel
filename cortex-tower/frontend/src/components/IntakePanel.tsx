import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  FileSearch,
  FileText,
  Loader2,
  PencilLine,
  MessagesSquare,
  RefreshCw,
  RotateCcw,
  ScanLine,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { callInbox } from "../services/api";
import { Card, Empty, Skel } from "../ui";
import { IntakeReview } from "./IntakeReview";
import { ROUTE_LABEL } from "../types";
import type { ChainMail, IntakeDetail, IntakeRun, IntakeThread, IntakeStep, IntakeSummary } from "../types";

/* ── helpers ──────────────────────────────────────────────────────────────── */
const ROUTE_BADGE: Record<string, string> = {
  new_order: "badge--brand",
  revision: "badge--warning",
  enquiry: "badge--info",
  chain_reply: "badge--positive",
  finance: "badge--outline",
  other: "badge--outline",
};
const STATUS_BADGE: Record<string, string> = {
  understood: "badge--info",
  simulated: "badge--warning",
  approved: "badge--positive",
  rejected: "badge--outline",
  blocked: "badge--critical",
  new: "badge--outline",
};

function confBadge(v?: number): string {
  const n = Number(v || 0);
  if (n >= 0.85) return "badge--positive";
  if (n >= 0.6) return "badge--warning";
  return "badge--critical";
}

function label(path: string): string {
  return path.split(".").slice(-1)[0].replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtBytes(n: number): string {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  const d = String(iso).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return String(iso).slice(0, 16);
  const [y, m, dd] = d.split("-");
  return `${dd} ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][Number(m) - 1]} ${y}`;
}

function fmtMoney(v: any, cur?: string): string {
  const n = Number(v);
  if (!v && v !== 0) return "—";
  return `${cur ? cur + " " : ""}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* the item code the plan will link — the same rule the backend uses, so the
   review pane shows exactly what will be written, never a guess */
function resolveItemCode(styleCode: string | undefined, size: string | undefined,
                         variants: string[] | undefined, styleItem: string | undefined): string {
  const code = (styleCode || "").toUpperCase();
  if (!code) return "";
  const vs = variants || [];
  if (size) {
    const exact = `${code}-${String(size).toUpperCase()}`;
    return vs.includes(exact) ? exact : "";
  }
  if (vs.length === 1) return vs[0];
  return vs.length ? "" : (styleItem || "");
}

type Tab = "summary" | "document" | "plan" | "chain" | "reply";

/* ── the panel ────────────────────────────────────────────────────────────── */
/** Set once per browser session: the mailbox is read when a screen opens. */
let _autoSynced = false;

export function IntakePanel({ notify, initialRunId }: {
  notify: (msg: string, opts?: { sticky?: boolean; link?: { url: string; label: string } }) => void;
  initialRunId?: number;
}) {
  const [threads, setThreads] = useState<IntakeThread[]>([]);
  const [selectedThread, setSelectedThread] = useState<string | null>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [summary, setSummary] = useState<IntakeSummary | null>(null);
  const [detail, setDetail] = useState<IntakeDetail | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  // "synced 4 min ago" — the mailbox is only read when a human asks or a screen opens
  const [freshness, setFreshness] = useState<string>("");
  const [tab, setTab] = useState<Tab>("summary");
  const [editing, setEditing] = useState<{ field: string; value: string } | null>(null);
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [showPdf, setShowPdf] = useState(false);
  const [pdfUrl, setPdfUrl] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [lineEdit, setLineEdit] = useState<{ i: number; k: string; v: string } | null>(null);

  const open = useCallback(async (id: number) => {
    setSelected(id);
    setTab("summary");
    setPage(0);
    setShowPdf(false);
    setPdfUrl("");
    setReading(true);
    try {
      const r = await callInbox("get_intake", { run_id: id, enrich: 1 });
      if (r.success && r.data?.run !== null) setDetail(r.data as IntakeDetail);
    } finally {
      setReading(false);
    }
  }, []);

  const load = useCallback(async (keep?: number) => {
    setLoading(true);
    try {
      const [q, s] = await Promise.all([
        callInbox("get_intake_queue", { limit: 200, group: 1 }),
        callInbox("get_intake_summary"),
      ]);
      const rows = (q.data?.threads || []) as IntakeThread[];
      if (q.success && q.data) setThreads(rows);
      if (s.success && s.data) {
        setSummary(s.data as IntakeSummary);
        setFreshness((s.data as any)?.freshness?.mail?.ago || "");
      }
      // open the first waiting document of the newest thread, so the pane is never blank
      const firstDoc = (rows[0]?.documents || []).find((d) => d.status !== "rejected") || rows[0]?.documents?.[0];
      const pick = keep ?? selected ?? initialRunId ?? firstDoc?.run_id ?? null;
      if (rows[0] && !selectedThread) setSelectedThread(rows[0].key);
      if (pick) await open(pick);
      else setDetail(null);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, initialRunId]);

  useEffect(() => {
    load();
    // The mailbox is read when the screen opens, once per browser session — this app has
    // no scheduler (the WIP heartbeat was removed on the owner's instruction, 2026-11-03).
    // Non-blocking: the pane paints from the local store first, then refreshes.
    if (!_autoSynced) {
      _autoSynced = true;
      callInbox("sync_inbox", { limit: 50 })
        .then(() => load())
        .catch(() => undefined);
    }
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, []);

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await callInbox("sync_inbox", { limit: 50 });
      const d = r.data || {};
      notify(r.success
        ? `Mailbox read: ${d.fetched ?? 0} new mail${d.remaining ? `, ${d.remaining} still queued` : ""}; ${d.flagged ?? 0} flagged`
        : `Sync failed: ${d.error || "unknown"}`);
      await load();
    } finally { setSyncing(false); }
  };

  const act = async (name: string, params: Record<string, any>, text: string) => {
    setBusy(name);
    try {
      const r = await callInbox(name, params);
      const d = r.data || {};
      if (d.ok === false) notify(`${text} failed: ${d.error || d.note || "unknown"}`, { sticky: true });
      else notify(d.note ? `${text}: ${d.note}` : `${text} done`, { sticky: !!d.note });
      await load(selected ?? undefined);
    } finally { setBusy(null); }
  };

  const thread = useMemo(
    () => threads.find((t) => t.key === selectedThread) || null, [threads, selectedThread]);

  const filtered = useMemo(() => {
    if (!filter) return threads;
    const f = filter.toLowerCase();
    return threads.filter((t) =>
      (t.buyer || "").toLowerCase().includes(f) ||
      (t.subject || "").toLowerCase().includes(f) ||
      (t.email || "").toLowerCase().includes(f) ||
      (t.documents || []).some((d) =>
        (d.route || "").toLowerCase().includes(f) ||
        (d.document || "").toLowerCase().includes(f) ||
        (d.summary || "").toLowerCase().includes(f)));
  }, [threads, filter]);

  /* A thread card opens its documents; the first click on a thread opens its first
     document so the right-hand pane always shows something real. */
  const pickThread = async (t: IntakeThread) => {
    setSelectedThread(t.key);
    const inside = (t.documents || []).some((d) => d.run_id === selected);
    if (inside) return;
    const doc = (t.documents || []).find((d) => d.status !== "rejected" && d.status !== "approved")
      || (t.documents || []).find((d) => d.status !== "rejected")
      || t.documents?.[0];
    if (doc) await open(doc.run_id);
  };

  const facts: any = detail?.facts || {};
  const c = facts.commercial || {};
  const d: any = detail?.dates || {};
  const avgConf = useMemo(() => {
    const vals = Object.values(facts.confidence || {}).map(Number).filter((n) => !isNaN(n));
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  }, [facts]);

  /* one cell of the colour/size table — click to correct it; saved through edit_intake (lines.N.key) */
  const lineCell = (i: number, k: string, value: any, num = false) => {
    const locked = !detail || detail.status === "approved" || detail.status === "rejected";
    if (lineEdit && lineEdit.i === i && lineEdit.k === k) {
      const save = () => {
        const raw = lineEdit.v.trim();
        const v = num ? Number(raw.replace(/,/g, "")) : raw;
        setLineEdit(null);
        if (num && Number.isNaN(v as number)) { notify("That is not a number — nothing changed."); return; }
        if (String(v) !== String(value ?? "")) void act("edit_intake", { run_id: detail!.id, field: `lines.${i}.${k}`, value: v }, "Line corrected");
      };
      return <input className="input input--sm" autoFocus style={{ width: num ? 90 : 120 }} value={lineEdit.v}
                    onChange={(e) => setLineEdit({ i, k, v: e.target.value })} onBlur={save}
                    onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setLineEdit(null); }} />;
    }
    const shown = value === null || value === undefined || value === "" ? "—"
      : num && k === "rate" ? fmtMoney(value, c.currency) : num ? Number(value).toLocaleString() : String(value);
    return locked ? <>{shown}</> : (
      <button type="button" className="linkish" title="Click to correct" style={{ background: "none", border: 0, padding: 0, color: "inherit", cursor: "pointer", textDecoration: "underline dotted" }}
              onClick={() => setLineEdit({ i, k, v: value === null || value === undefined ? "" : String(value) })}>{shown}</button>
    );
  };

  const field = (path: string, value: any, opts: { edit?: boolean; tone?: string } = {}) => {
    if (value === null || value === undefined || value === "") return null;
    const conf = facts.confidence?.[path];
    const isEditing = editing?.field === path;
    return (
      <div className="fld" key={path}>
        <div className="fld__k">{label(path)}</div>
        <div className={`fld__v${opts.tone ? ` is-${opts.tone}` : ""}`}>
          {isEditing ? (
            <span className="fld__edit">
              <input
                className="input" autoFocus value={editing.value}
                onChange={(e) => setEditing({ ...editing, value: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    act("edit_intake", { run_id: detail!.id, field: path, value: editing.value }, "Field corrected");
                    setEditing(null);
                  }
                  if (e.key === "Escape") setEditing(null);
                }}
              />
              <button className="btn btn--sm" onClick={() => { act("edit_intake", { run_id: detail!.id, field: path, value: editing!.value }, "Field corrected"); setEditing(null); }}><Check size={12} /></button>
              <button className="btn btn--sm" onClick={() => setEditing(null)}><X size={12} /></button>
            </span>
          ) : (
            <>
              <span>{String(value)}</span>
              {conf !== undefined && (
                <span className={`badge ${confBadge(conf)}`} title="how sure the reader is">{Math.round(Number(conf) * 100)}%</span>
              )}
              {opts.edit !== false && detail!.status !== "approved" && (
                <button className="fld__pen" title="Correct this field" onClick={() => setEditing({ field: path, value: String(value) })}>
                  <PencilLine size={11} />
                </button>
              )}
            </>
          )}
        </div>
      </div>
    );
  };

  /* ── render ─────────────────────────────────────────────────────────────── */
  return (
    <div className="intake">
      {reviewing && detail && (
        <IntakeReview runId={detail.id} onClose={() => setReviewing(false)}
          onDone={(msg) => { setReviewing(false); notify(msg, { sticky: true }); void load(detail.id); }} />
      )}
      <div className="intake__head">
        <div>
          <div className="intake__title"><ScanLine size={16} /> Order intake — mail → process</div>
          <div className="intake__sub">
            Every buyer sends its own sheet. The Tower opens it, puts every number where it can prove it
            came from, and prepares the ERP drafts. <b>Nothing is created until you approve.</b>
          </div>
        </div>
        <div className="intake__head-actions">
          <input className="input intake__search" placeholder="Filter by buyer, PO, route…"
                 value={filter} onChange={(e) => setFilter(e.target.value)} />
          <span className="muted" style={{ fontSize: 12, marginRight: 8, whiteSpace: "nowrap" }}>
            {freshness ? `synced ${freshness}` : "never synced"}
          </span>
          <button className="btn btn--sm" onClick={sync} disabled={syncing}>
            {syncing ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />}
            {syncing ? "Reading mailbox…" : "Read mailbox"}
          </button>
        </div>
      </div>

      {summary && (
        <div className="intake__kpis">
          <Kpi label="Understood" value={summary.understood} />
          <Kpi label="Ready to approve" value={summary.ready_to_approve} tone="positive" />
          <Kpi label="Approved" value={summary.approved} tone="positive" />
          <Kpi label="Rejected" value={summary.rejected} />
          <Kpi label="Blocked steps" value={summary.blocked} tone="warning" />
        </div>
      )}

      <div className="intake__body">
        {/* left column — one plain card per MAIL THREAD, nothing else ─────────
           The documents belong to the RIGHT pane (master–detail): a list you scan,
           and the thing you picked beside it. Expanding rows inside a card made the
           left column do two jobs at once and read as noise. */}
        <div className="intake__queue">
          {loading && !threads.length && [0, 1, 2].map((i) => <Skel key={i} h={58} style={{ marginBottom: 8 }} />)}
          {!loading && !filtered.length && (
            <Empty icon={<FileSearch size={18} />} title="Nothing in the intake queue"
              hint="Press “Read mailbox” — the Tower reads the mail and opens one card per thread." />
          )}
          {filtered.map((t) => {
            const c: any = t.counts || {};
            return (
              <button key={t.key} className={`intake__card${selectedThread === t.key ? " is-active" : ""}`}
                      onClick={() => void pickThread(t)}>
                <div className="intake__card-top">
                  <span className="badge badge--outline"><MessagesSquare size={10} /> {t.mails} mail{t.mails > 1 ? "s" : ""}</span>
                  {c.waiting > 0 && <span className="badge badge--warning">{c.waiting} to decide</span>}
                  {c.approved > 0 && <span className="badge badge--positive">{c.approved} approved</span>}
                  {c.blocked_steps > 0 && (
                    <span className="badge badge--critical"><AlertTriangle size={10} /> {c.blocked_steps}</span>
                  )}
                </div>
                <div className="intake__card-subject">{(t.buyer || t.subject || "(no subject)").slice(0, 74)}</div>
                <div className="intake__card-foot">
                  <span>{t.email}</span>
                  <span>{c.documents} doc{c.documents > 1 ? "s" : ""} · {fmtDate(t.last_at)}</span>
                </div>
              </button>
            );
          })}
        </div>

        {/* detail */}
        <div className="intake__detail">
          {reading && (
            <div className="intake__reading">
              <Loader2 size={14} className="spin" /> Reading the document…
              <span className="muted">the model reads the page the first time a card is opened</span>
            </div>
          )}
          {!detail && !loading && !reading && (
            <Empty title="Select an intake" hint="Each card is one document the Tower has read." />
          )}

          {thread && (
            <div className="intake__threadbar">
              <div className="intake__threadbar-head">
                <div>
                  <div className="intake__threadbar-title">{thread.buyer || thread.subject}</div>
                  <div className="muted" style={{ fontSize: 11.5 }}>
                    {thread.email} · {thread.mails} mail{thread.mails > 1 ? "s" : ""} ·{" "}
                    {(thread.documents || []).length} document(s) · last {fmtDate(thread.last_at)}
                  </div>
                </div>
                <button className="btn btn--sm" disabled={busy === "docs"} onClick={() => setShowDocs(!showDocs)}>
                  <ChevronRight size={12} style={{ transform: showDocs ? "rotate(90deg)" : "none" }} />
                  {(thread.documents || []).length} document(s)
                </button>
              </div>
              {/* what is in this thread — the thing the left card must not try to show */}
              {showDocs && (
                <div className="intake__doclist">
                  {(thread.documents || []).map((doc) => (
                    <button key={doc.run_id}
                            className={`intake__docrow${selected === doc.run_id ? " is-active" : ""}`}
                            onClick={() => void open(doc.run_id)}>
                      <span className={`badge ${ROUTE_BADGE[doc.route] || "badge--outline"}`}>
                        {ROUTE_LABEL[doc.route] || doc.route}
                      </span>
                      <span className="intake__doc-name">{(doc.document || doc.summary || "—").slice(0, 60)}</span>
                      <span className={`intake__doc-state is-${doc.status}`}>{doc.status}</span>
                      {doc.blocked > 0 && <span className="intake__doc-blk"><AlertTriangle size={10} /> {doc.blocked}</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {detail && !reading && (
            <>
              {/* ── header: identity, dates, actions ───────────────────────── */}
              <Card
                title={<span className="intake__dtitle">{detail.mail?.subject || detail.summary}</span>}
                sub={<span>
                  {detail.document?.filename} · {detail.document?.pages || 0} page(s) ·{" "}
                  {detail.document?.chars || 0} chars read · read by {detail.extractor || "patterns"}
                </span>}
                actions={
                  <>
                    <button className="btn btn--sm" disabled={!!busy}
                            onClick={() => act("understand_intake", { run_id: detail.id, use_llm: 1 }, "Re-read with the model")}>
                      {busy === "understand_intake" ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />} Re-read
                    </button>
                    <button className="btn btn--sm" disabled={!!busy}
                            onClick={() => act("simulate_intake", { run_id: detail.id }, "Simulate")}>
                      {busy === "simulate_intake" ? <Loader2 size={13} className="spin" /> : <FileSearch size={13} />} Simulate
                    </button>
                    {detail.status !== "approved" && detail.status !== "rejected" && (
                      <>
                        <button className="btn btn--sm btn--primary" disabled={!!busy}
                                onClick={() => setReviewing(true)}
                                title="See and change every value first; nothing is written until you confirm">
                          <Check size={13} /> Review &amp; approve
                        </button>
                        <button className="btn btn--sm" disabled={!!busy}
                                onClick={() => act("reject_intake", { run_id: detail.id, reason: "not an order" }, "Reject")}>
                          <Ban size={13} /> Reject
                        </button>
                      </>
                    )}
                    {detail.status === "approved" && (
                      <button className="btn btn--sm" disabled={!!busy}
                              onClick={() => act("rollback_intake", { run_id: detail.id }, "Rollback")}>
                        <RotateCcw size={13} /> Roll back
                      </button>
                    )}
                  </>
                }
              >
                {/* the numbers a merchandiser checks first */}
                <div className="dstrip">
                  <Cell k="Buyer" v={(facts.buyer || {}).name || "—"} />
                  <Cell k="PO" v={(facts.po || {}).number || "—"} />
                  <Cell k="PO date" v={fmtDate(d.po_date)} />
                  <Cell k="Ship / X-factory" v={fmtDate(d.ship_date)} tone={d.ship_in_past ? "warn" : undefined} />
                  <Cell k="Qty" v={c.total_qty ? `${Number(c.total_qty).toLocaleString()} pcs` : "—"} />
                  <Cell k="Rate" v={c.rate ? fmtMoney(c.rate, c.currency) : "—"} />
                  <Cell k="Value" v={c.total_value ? fmtMoney(c.total_value, c.currency) : "—"} />
                </div>

                {/* the date chain, and where it disagrees with today */}
                <div className="dtime">
                  <span className="dtime__node"><Clock size={12} /> received <b>{fmtDate(d.received)}</b></span>
                  <span className="dtime__arrow">→</span>
                  <span className="dtime__node"><CalendarDays size={12} /> PO dated <b>{fmtDate(d.po_date)}</b></span>
                  <span className="dtime__arrow">→</span>
                  <span className={`dtime__node${d.ship_in_past ? " is-warn" : ""}`}>
                    <CalendarDays size={12} /> ships <b>{fmtDate(d.ship_date)}</b>
                  </span>
                  {d.po_to_ship_days !== null && d.po_to_ship_days !== undefined && (
                    <span className="dtime__note">{d.po_to_ship_days} days PO → ship</span>
                  )}
                  {d.lead_time_days ? <span className="dtime__note">paper says lead time {d.lead_time_days} d</span> : null}
                  {d.ship_in_past && <span className="badge badge--warning">ship date is in the past</span>}
                </div>

                {(d.edited || []).length > 0 && (
                  <div className="dnote">
                    Corrected by a human: {d.edited.map(label).join(" · ")} — the paper's reading was kept underneath.
                  </div>
                )}

                {/* tabs */}
                <div className="intake__tabs">
                  {([
                    ["summary", "Summary"],
                    ["document", "Their document"],
                    ["plan", "What it will create"],
                    ...(detail.chain?.id ? [["chain", `The thread (${detail.chain.timeline_count || 1})`] as [Tab, string]] : []),
                    ["reply", "The reply"],
                  ] as [Tab, string][]).map(([id, text]) => (
                    <button key={id} className={`intake__tab${tab === id ? " is-active" : ""}`} onClick={() => setTab(id)}>
                      {text}
                    </button>
                  ))}
                  <span className="muted" style={{ marginLeft: "auto", fontSize: 11.5 }}>
                    {Math.round(avgConf * (avgConf <= 1 ? 100 : 1))}% average reading confidence
                  </span>
                </div>

                {/* ── summary ─────────────────────────────────────────────── */}
                {tab === "summary" && (
                  <div className="facts">
                    <Section title="From (buyer)">
                      {field("buyer.name", facts.buyer?.name)}
                      {field("buyer.country", facts.buyer?.country)}
                      {field("buyer.address", facts.buyer?.address)}
                      {field("buyer.phone", facts.buyer?.phone)}
                      {field("buyer.contact", facts.buyer?.contact)}
                      {field("buyer.email", facts.buyer?.email)}
                    </Section>

                    <Section title="To (our company / vendor)">
                      {field("to.name", facts.to?.name)}
                      {field("to.address", facts.to?.address)}
                      {field("to.phone", facts.to?.phone)}
                      {field("to.email", facts.to?.email)}
                    </Section>

                    <Section title="The order">
                      {field("po.number", facts.po?.number)}
                      {field("po.date", facts.po?.date)}
                      {field("po.reference", facts.po?.reference)}
                      {field("season", facts.season)}
                      {field("ship_date", facts.ship_date)}
                      {d.lead_time_days ? <div className="fld"><div className="fld__k">Lead time (paper)</div><div className="fld__v">{d.lead_time_days} days</div></div> : null}
                    </Section>

                    <Section title="Commercials">
                      {field("commercial.currency", c.currency)}
                      {field("commercial.rate", c.rate && fmtMoney(c.rate, c.currency))}
                      {field("commercial.fabric_rate", c.fabric_rate && fmtMoney(c.fabric_rate, c.currency))}
                      {field("commercial.total_qty", c.total_qty && `${Number(c.total_qty).toLocaleString()} pcs`)}
                      {field("commercial.total_value", c.total_value && fmtMoney(c.total_value, c.currency))}
                      {field("commercial.incoterm", c.incoterm)}
                      {field("commercial.named_place", c.named_place)}
                      {field("commercial.payment_terms", c.payment_terms)}
                    </Section>

                    <Section title="Style & fabric">
                      {field("style.code", facts.style?.code)}
                      {field("style.description", facts.style?.description)}
                      {field("style.fabric", facts.style?.fabric)}
                      {field("style.composition", facts.style?.composition)}
                      {field("style.gsm", facts.style?.gsm)}
                      {field("style.fabric_code", facts.style?.fabric_code)}
                      {field("style.yield_per_pc", facts.style?.yield_per_pc)}
                    </Section>

                    <Section title="Quality & packing">
                      {field("quality.aql_major", facts.quality?.aql_major)}
                      {field("quality.aql_minor", facts.quality?.aql_minor)}
                      {field("quality.carton_ratio", facts.quality?.carton_ratio)}
                    </Section>

                    {(facts.lines || []).length > 0 && (
                      <div className="facts__wide">
                        <div className="facts__h">Colour / size lines as read <span className="muted" style={{ fontWeight: 400 }}>· click a value to correct it</span></div>
                        <table className="ltable">
                          <thead><tr><th>Colour</th><th>Shade</th><th>Qty</th><th>Rate</th><th>Item code (ours)</th><th>Size grid</th></tr></thead>
                          <tbody>
                            {(facts.lines || []).map((l: any, i: number) => (
                              <tr key={i}>
                                <td>{lineCell(i, "colour", l.colour)}</td>
                                <td>{lineCell(i, "shade", l.shade)}</td>
                                <td>{lineCell(i, "qty", l.qty, true)}</td>
                                <td>{lineCell(i, "rate", l.rate, true)}</td>
                                <td>{resolveItemCode(facts.style?.code, l.size,
                                                       detail.matches?.style_variants,
                                                       detail.matches?.style_item) || <span className="muted">new</span>}</td>
                                <td>
                                  {l.size_grid
                                    ? Object.entries(l.size_grid).map(([s, q]) => (
                                        <span key={s} className="szchip">{s} {String(q)}</span>
                                      ))
                                    : <span className="muted">not printed</span>}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {((facts.asks || []).length > 0 || (facts.claims || []).length > 0) && (
                      <div className="facts__wide facts__notes">
                        {(facts.asks || []).length > 0 && (
                          <div>
                            <div className="facts__h">They asked us</div>
                            {(facts.asks || []).map((a: string, i: number) => <div key={i} className="fact-ask">→ {a}</div>)}
                          </div>
                        )}
                        {(facts.claims || []).length > 0 && (
                          <div>
                            <div className="facts__h">Instructions that bind production</div>
                            {(facts.claims || []).map((x: string, i: number) => <div key={i} className="fact-claim">• {x}</div>)}
                          </div>
                        )}
                      </div>
                    )}

                    {(detail.missing || []).length > 0 && (
                      <div className="facts__wide">
                        <div className="intake__missing"><AlertTriangle size={13} /> Not on the paper: {detail.missing.join(" · ")}</div>
                      </div>
                    )}
                  </div>
                )}

                {/* ── their document ──────────────────────────────────────── */}
                {tab === "document" && (
                  <div className="docview">
                    <div className="docview__bar">
                      <FileText size={13} />
                      <b>{detail.document?.filename || "no attachment"}</b>
                      <span className="muted">
                        {detail.document?.parser || "—"} · {detail.document?.pages || 0} page(s) ·{" "}
                        {detail.document?.chars || 0} chars · {fmtBytes(detail.document?.size || 0)}
                      </span>
                      {detail.document?.needs_ocr && <span className="badge badge--warning">scan — needs OCR</span>}
                      <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                        {(detail.pages || []).length > 1 && !showPdf && (
                          <>
                            <button className="btn btn--sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
                              <ChevronLeft size={12} />
                            </button>
                            <span style={{ fontSize: 12 }}>page {page + 1} / {detail.pages!.length}</span>
                            <button className="btn btn--sm" onClick={() => setPage((p) => Math.min(detail.pages!.length - 1, p + 1))}
                                    disabled={page >= (detail.pages!.length - 1)}>
                              <ChevronRight size={12} />
                            </button>
                          </>
                        )}
                        {detail.document?.has_pdf ? (
                          <button className="btn btn--sm" onClick={async () => {
                            if (showPdf) { setShowPdf(false); return; }
                            if (!pdfUrl) {
                              const r = await callInbox("get_intake_document", { run_id: detail.id });
                              if (r.success && r.data?.data_url) setPdfUrl(r.data.data_url);
                              else { notify(`Cannot show the original: ${r.data?.error || "unknown"}`); return; }
                            }
                            setShowPdf(true);
                          }}>
                            {showPdf ? "Show as text" : "Show the original PDF"}
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {showPdf && pdfUrl ? (
                      <iframe title="original document" src={pdfUrl} className="docview__pdf" />
                    ) : (detail.pages || []).length ? (
                      <div className="docview__paper">
                        {(detail.pages![page]?.lines || []).map((line: string, i: number) => (
                          <div key={i} className="docview__line">{line || "\u00a0"}</div>
                        ))}
                      </div>
                    ) : (
                      <div className="docview__empty">
                        No page to show — the facts came from the mail body only.
                      </div>
                    )}

                    <div className="docview__mail">
                      <div className="facts__h">The email</div>
                      <pre>{detail.mail.body_text || "(empty)"}</pre>
                    </div>
                  </div>
                )}

                {/* ── plan ────────────────────────────────────────────────── */}
                {tab === "plan" && (
                  <div className="intake__plan">
                    {detail.status !== "approved" && detail.status !== "rejected" && (
                      <div className="intake__step" style={{ alignItems: "center" }}>
                        <div style={{ flex: 1 }}>
                          <div className="intake__step-label">Every value below can be changed before anything is written.</div>
                          <div className="intake__step-reason">Open the review to see each field and row the ERP will receive, edit any of them, then confirm.</div>
                        </div>
                        <button className="btn btn--sm btn--primary" onClick={() => setReviewing(true)}><PencilLine size={13} /> Review &amp; edit values</button>
                      </div>
                    )}
                    {detail.plan.map((s: IntakeStep) => (
                      <div key={s.key} className={`intake__step${s.status === "blocked" ? " is-blocked" : ""}`}>
                        <span className="intake__step-no">{s.seq}</span>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div className="intake__step-label">{s.label}</div>
                          {s.reason && <div className="intake__step-reason">{s.reason}</div>}
                          {/* the buyer gate: a 60-85 % name match is a question, and this is
                              where a human answers it — link the Customer, or create a new one */}
                          {s.key === "customer" && s.status === "blocked" &&
                            (detail.matches?.customer_candidates || []).length > 0 && (
                            <div className="intake__step-actions">
                              {(detail.matches.customer_candidates as { name: string; score: number }[]).map((c) => (
                                <button key={c.name} className="btn btn--sm btn--primary" disabled={!!busy}
                                        onClick={() => act("set_intake_customer", { run_id: detail.id, customer: c.name },
                                                           `Linked to ${c.name}`)}>
                                  <Check size={12} /> It is {c.name}
                                </button>
                              ))}
                              <button className="btn btn--sm" disabled={!!busy}
                                      onClick={() => act("set_intake_customer", { run_id: detail.id, create: 1 },
                                                         "Will create a new Customer")}>
                                It is a different company — create it
                              </button>
                            </div>
                          )}
                          {s.kind === "ingest_pack" && s.status !== "blocked" && (
                            <div className="intake__step-actions">
                              <button className="btn btn--sm btn--primary" disabled={!!busy}
                                      onClick={() => act("ingest_chain_pack", { run_id: detail.id, apply: 1 },
                                                         "Pack ingested")}>
                                {busy === "ingest_chain_pack" ? <Loader2 size={12} className="spin" /> : <ScanLine size={12} />}
                                Read the pack into the ERP now
                              </button>
                              <span className="muted" style={{ fontSize: 11.5 }}>
                                Buyer Tech Pack + one BOM per size, through the same builder the desk uses
                              </span>
                            </div>
                          )}
                        </div>
                        <span className={`badge ${s.status === "blocked" ? "badge--warning"
                          : (s.status as string) === "skipped" ? "badge--outline"
                          : (s as any).existing ? "badge--info" : "badge--positive"}`}>
                          {s.status === "blocked" ? "blocked"
                            : (s.status as string) === "skipped" ? "not used on this ERP"
                            : (s as any).existing ? `will link ${(s as any).existing}` : "will create"}
                        </span>
                      </div>
                    ))}
                    {(detail.created_refs || []).length > 0 && (
                      <div className="intake__created">
                        <div className="facts__h">Created by this approval</div>
                        {detail.created_refs.map((r) => (
                          <div key={r.doctype + r.name} className="intake__ref">
                            <CheckCircle2 size={12} /> {r.doctype} <b>{r.name}</b>
                          </div>
                        ))}
                        {detail.result_note && <pre className="intake__note-pre">{detail.result_note}</pre>}
                        {/* An approval that created nothing but to-dos left the deal where it was.
                            Reopening re-plans it against today's ERP; the backend refuses when a
                            real record was made, because a second approve would double it. */}
                        {detail.status === "approved" &&
                          (detail.created_refs || []).every((r) => r.doctype === "Task") && (
                          <button className="btn btn--sm" style={{ marginTop: 8 }} disabled={!!busy}
                                  onClick={() => act("reopen_intake", { run_id: detail.id }, "Re-planned")}>
                            <RotateCcw size={13} /> It only made to-dos — re-plan it
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* ── the thread: answer the buyer, and take the pack ────────── */}
                {tab === "chain" && detail.chain?.id && (
                  <ChainTab runId={detail.id} notify={notify} ack={detail.ack}
                            customer={(detail.matches?.customer as string) || detail.chain.customer || ""}
                            plan={detail.plan} busy={busy} act={act} />
                )}

                {/* ── reply ───────────────────────────────────────────────── */}
                {tab === "reply" && (
                  <div className="intake__reply">
                    <div className="intake__reply-head">
                      <div>
                        <div className="facts__h">Draft acknowledgement</div>
                        <div className="muted">Every number here comes from the record — nothing is invented.</div>
                      </div>
                      <span className={`badge ${detail.ack?.grounding?.ok ? "badge--positive" : "badge--critical"}`}>
                        {detail.ack?.grounding?.ok ? "grounded" : `unsourced: ${(detail.ack?.grounding?.unsourced || []).join(", ")}`}
                      </span>
                    </div>
                    <div className="intake__reply-subject">{detail.ack?.subject}</div>
                    <pre className="intake__att-text">{detail.ack?.body}</pre>
                    <button className="btn btn--sm" disabled={!!busy || !detail.ack?.grounding?.ok}
                            onClick={() => act("create_intake_ack", { run_id: detail.id }, "Acknowledgement drafted")}>
                      <Send size={13} /> Put it in the outbound queue
                    </button>
                    <div className="muted" style={{ marginTop: 6 }}>
                      It is never sent from here — it lands in Outbound Mail for an explicit approval.
                    </div>
                  </div>
                )}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── the thread ──────────────────────────────────────────────────────────── */
function ChainTab({ runId, notify, ack, customer, plan, busy, act }: {
  runId: number;
  notify: (msg: string, opts?: { sticky?: boolean }) => void;
  ack?: { subject: string; body: string; grounding?: { ok: boolean; unsourced: string[] } };
  customer: string;
  plan: IntakeStep[];
  busy: string | null;
  act: (name: string, params: Record<string, any>, text: string) => Promise<void>;
}) {
  const [data, setData] = useState<{ chain: any; timeline: ChainMail[]; reply_to: string; reply_subject: string; in_thread: boolean; stale?: string[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [unsourced, setUnsourced] = useState<string[] | null>(null);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await callInbox("get_mail_chain", { run_id: runId });
      if (r.success && r.data?.ok) {
        setData(r.data);
        setSubject((s) => s || r.data.reply_subject || "");
      } else notify(`The thread could not be read: ${r.data?.error || "unknown"}`);
    } finally { setLoading(false); }
  }, [runId, notify]);

  useEffect(() => { void load(); }, [load]);

  /* Grounding INFORMS here — it does not block. The reply is written by a human quoting a
     price that does not exist in any record yet, so a wall would refuse the normal case.
     The figures that are not on the record are shown before sending and stored with the
     draft, so the record says exactly what was never sourced. */
  const send = async (confirm: number) => {
    if (!body.trim()) { notify("Write the reply first."); return; }
    setSending(true);
    try {
      const r = await callInbox("send_chain_reply", {
        run_id: runId, subject, body, confirm, enforce_grounding: 0, actor: "Ops Manager",
      });
      /* A failed CALL used to look exactly like nothing happening: no toast, no error,
         the button just stopped spinning. Say it out loud (2026-11-03). */
      if (!r.success) {
        notify(`The send did not reach the server: ${r.message || "unknown error"}`, { sticky: true });
        return;
      }
      const d = r.data || {};
      if (d.error === "names_the_platform") { notify(d.message || "Remove the platform name.", { sticky: true }); return; }
      if (d.error === "ungrounded") { setUnsourced(d.unsourced || []); setConfirming(true); return; }
      if (d.error) { notify(`Not sent: ${d.error}`, { sticky: true }); return; }
      if (d.confirmation_required) {
        setUnsourced(d.unsourced || []);
        setConfirming(true);
        return;
      }
      if (d.status === "sent") {
        const n = (d.unsourced || []).length;
        notify(d.already ? "That reply had already gone out."
          : `Replied to ${d.draft?.to_email || "the buyer"} — in the thread`
            + (n ? ` · ${n} figure(s) recorded as not on the record` : "."));
        setBody("");
        setConfirming(false);
        setUnsourced(null);
        await load();
        return;
      }
      notify(`Not sent — the server answered ${d.status || "nothing"}${d.error ? `: ${d.error}` : ""}`,
             { sticky: true });
    } catch (e: any) {
      notify(`Not sent: ${e?.message || "the request failed"}`, { sticky: true });
    } finally { setSending(false); }
  };

  const pack = (plan || []).find((s) => s.kind === "ingest_pack");

  return (
    <div className="intake__chain">
      {loading && <div className="intake__reading"><Loader2 size={14} className="spin" /> Reading the thread…</div>}

      {/* the chain names ERP records; if one was deleted in the ERP, say so here rather
          than letting the card point at a ghost (2026-11-04, D-132) */}
      {!!(data?.stale && data.stale.length) && (
        <div className="chain__pack is-blocked" style={{ marginBottom: 8 }}>
          <AlertTriangle size={14} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <b>Deleted in the ERP</b>
            <div className="muted" style={{ fontSize: 12 }}>
              this thread pointed at {data.stale.join(", ")} — the record is gone, so approving
              will create it again rather than skip it
            </div>
          </div>
        </div>
      )}

      {!!pack && (
        <div className={`chain__pack${pack.status === "blocked" ? " is-blocked" : ""}`}>
          <ScanLine size={14} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <b>{pack.status === "blocked" ? "No tech pack in this thread yet" : "The tech pack is here"}</b>
            <div className="muted" style={{ fontSize: 12 }}>{pack.reason || pack.label}</div>
          </div>
          {pack.status !== "blocked" && (
            <button className="btn btn--sm btn--primary" disabled={!!busy}
                    onClick={() => act("ingest_chain_pack", { run_id: runId, apply: 1 }, "Pack ingested")}>
              <ScanLine size={12} /> Ingest it
            </button>
          )}
        </div>
      )}

      <div className="chain__timeline">
        {(data?.timeline || []).map((m) => (
          <div key={`${m.dir}-${m.id}`} className={`chain__msg is-${m.dir}`}>
            <div className="chain__msg-head">
              <span className={`badge ${m.dir === "in" ? "badge--info" : "badge--positive"}`}>
                {m.dir === "in" ? "in" : m.status === "sent" ? "sent" : m.status || "draft"}
              </span>
              <b>{m.dir === "in" ? m.from : `us → ${m.to}`}</b>
              <span className="muted">{fmtDate(m.at)}{m.at && m.at.length > 10 ? " " + m.at.slice(11, 16) : ""}</span>
              {m.route && <span className="muted">· {ROUTE_LABEL[m.route] || m.route}</span>}
            </div>
            <div className="chain__msg-subject">{m.subject}</div>
            <pre className="chain__msg-body">{(m.body || "").slice(0, 1200)}</pre>
            {(m.attachments || []).length > 0 && (
              <div className="chain__msg-att">
                {m.attachments.map((a, i) => (
                  <span key={i} className="badge badge--outline"><FileText size={10} /> {a.filename || "attachment"}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        {!loading && !(data?.timeline || []).length && (
          <Empty title="Nothing in this thread yet" hint="The conversation starts with the mail above." />
        )}
      </div>

      <div className="chain__compose">
        <div className="chain__compose-head">
          <div className="facts__h">Answer the buyer — in their thread</div>
          <span className={`badge ${data?.in_thread ? "badge--positive" : "badge--warning"}`}>
            {data?.in_thread ? "threaded" : "no message id — it will start a new thread"}
          </span>
        </div>
        <div className="chain__to">to <b>{data?.reply_to || "—"}</b>{customer ? <> · buyer <b>{customer}</b></> : null}</div>
        <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject" />
        <textarea className="input chain__body" rows={8} value={body}
                  onChange={(e) => { setBody(e.target.value); setUnsourced(null); setConfirming(false); }}
                  placeholder="Write the answer. Every number must come from the record — the Tower checks." />
        <div className="chain__compose-actions">
          {!!ack?.body && (
            <button className="btn btn--sm" onClick={() => { setSubject(ack.subject); setBody(ack.body); setUnsourced(null); setConfirming(false); }}>
              <Sparkles size={12} /> Start from the drafted acknowledgement
            </button>
          )}
          <button className="btn btn--sm btn--primary" disabled={sending || !!busy} onClick={() => void send(0)}>
            {sending ? <Loader2 size={12} className="spin" /> : <Send size={12} />} Review &amp; send
          </button>
        </div>

        {confirming && (
          <div className="chain__confirm">
            <b>Send this to {data?.reply_to}?</b>
            <div className="muted">It goes into the thread the buyer already has — their answer comes back here.</div>
            {!!unsourced?.length && (
              <div className="chain__warn" style={{ marginTop: 6 }}>
                <AlertTriangle size={13} /> <b>{unsourced.length}</b> figure(s) in your text are not on any record:{" "}
                <b>{unsourced.slice(0, 14).join(", ")}{unsourced.length > 14 ? " …" : ""}</b>
                <div style={{ marginTop: 3 }}>
                  Fine if you are quoting a price you are about to issue — it is written on the mail as
                  not-on-record. If one of them should match a record, fix it and review again.
                </div>
              </div>
            )}
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <button className="btn btn--sm btn--primary" disabled={sending} onClick={() => void send(1)}>
                {sending ? <Loader2 size={12} className="spin" /> : <Send size={12} />} Yes, send it
              </button>
              <button className="btn btn--sm" onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── small pieces ─────────────────────────────────────────────────────────── */
function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={`intake__kpi${tone ? ` is-${tone}` : ""}`}>
      <div className="intake__kpi-v">{value ?? 0}</div>
      <div className="intake__kpi-l">{label}</div>
    </div>
  );
}

function Cell({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <div className={`dcell${tone ? ` is-${tone}` : ""}`}>
      <div className="dcell__k">{k}</div>
      <div className="dcell__v">{v}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const items = React.Children.toArray(children).filter(Boolean);
  if (!items.length) return null;
  return (
    <div className="facts__group">
      <div className="facts__h">{title}</div>
      {items}
    </div>
  );
}
