import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  FileText,
  Loader2,
  RefreshCw,
  ScanLine,
  Sparkles,
  Tag,
  XCircle,
} from "lucide-react";
import { callInbox } from "../services/api";
import { Card, Empty, Skel } from "../ui";
import { fmtDate, fmtNum } from "../types";

/* ── the register ─────────────────────────────────────────────────────────
   An enquiry used to end at the intake card. This is where it sits afterwards:
   one row per enquiry, and per style, what the ERP already knows — because a buyer
   re-asking for a style we made two seasons ago is the easiest enquiry there is,
   and the answer (the cost sheet, the BOM, the pack, the last price) is on file. */

export interface InquiryLine {
  style: string;
  description?: string;
  qty?: number | null;
  verdict: "made" | "costed" | "on_file" | "new";
  label: string;
  quote_ready?: boolean;
  item?: string | null;
  sizes?: string[];
  uom?: string;
  item_group?: string;
  price?: { price_list_rate?: number; currency?: string; valid_from?: string } | null;
  cost?: { name?: string; total_fob?: number; locked_fob?: number; status?: string; valid_till?: string } | null;
  bom?: { count: number; names?: string[]; active?: number };
  tech_pack?: { name?: string; pack_revision?: string; status?: string } | null;
  orders?: { sales_order?: string; customer?: string; date?: string; status?: string;
             item?: string; qty?: number; rate?: number; currency?: string }[];
  order_count?: number;
  last_order?: { sales_order?: string; date?: string; rate?: number; qty?: number; currency?: string; status?: string } | null;
  last_price?: number | null;
  currency?: string;
  errors?: string[];
}

export interface BuyerInquiry {
  id: number;
  run_id?: number | null;
  chain_id?: number | null;
  subject: string;
  buyer_name: string;
  buyer_email: string;
  customer: string;
  opportunity: string;
  received_at: string;
  quote_due: string;
  quote_due_raw?: string;
  quote_due_note?: string;
  target_ship: string;
  currency: string;
  total_qty: number;
  status: string;
  asks: string[];
  missing: string[];
  lines: InquiryLine[];
  styles: string[];
  old_styles: string[];
  new_styles: string[];
  note?: string;
  history_at?: string;
  /** Which ERP records this enquiry still points at — checked live, never assumed. */
  pointers?: { verified: string[]; missing: string[]; unavailable: string[]; state: Record<string, string> };
  stale?: string[];
}

export interface InquirySummary {
  total: number;
  new: number;
  costing: number;
  quoted: number;
  won: number;
  lost: number;
  with_old_styles: number;
  quote_ready: number;
  styles: number;
}

const VERDICT: Record<string, { badge: string; text: string; hint: string }> = {
  made: { badge: "badge--positive", text: "made before", hint: "we have an order line for this style" },
  costed: { badge: "badge--info", text: "costed", hint: "a cost sheet or a price exists — never ordered" },
  on_file: { badge: "badge--outline", text: "on file", hint: "the style is in the item master, never costed" },
  new: { badge: "badge--warning", text: "new style", hint: "nothing on file — price it from costing" },
};

const STATUS_BADGE: Record<string, string> = {
  new: "badge--warning", costing: "badge--info", quoted: "badge--brand",
  won: "badge--positive", lost: "badge--outline", dismissed: "badge--outline",
};

const money = (v: any, cur?: string) =>
  v === null || v === undefined || v === "" ? "—"
    : `${cur ? cur + " " : ""}${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function daysTo(iso?: string): number | null {
  if (!iso) return null;
  const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
  if (isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 86400000);
}

export function EnquiriesView({ notify, onOpenIntake }: {
  notify: (msg: string, opts?: { sticky?: boolean; link?: { url: string; label: string } }) => void;
  onOpenIntake?: (runId: number) => void;
}) {
  const [rows, setRows] = useState<BuyerInquiry[]>([]);
  const [summary, setSummary] = useState<InquirySummary | null>(null);
  const [detail, setDetail] = useState<BuyerInquiry | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async (refresh = 0) => {
    setLoading(true);
    try {
      const r = await callInbox("get_buyer_inquiries", { refresh });
      if (r.success && r.data?.ok) {
        setRows(r.data.items || []);
        setSummary(r.data.summary || null);
        if (refresh) notify("The ERP was re-read for every style on the register.");
      } else {
        notify(`The register could not be read: ${r.data?.error || r.message || "unknown"}`,
               { sticky: true });
      }
    } catch (e: any) {
      notify(`The register could not be read: ${e?.message || "the request failed"}`, { sticky: true });
    } finally { setLoading(false); }
  }, [notify]);

  useEffect(() => { void load(0); }, [load]);

  const open = useCallback(async (id: number) => {
    setSelected(id);
    setDetail(null);
    setBusy("open");
    try {
      const r = await callInbox("get_buyer_inquiry", { inquiry_id: id });
      if (r.success && r.data?.ok) setDetail(r.data as BuyerInquiry);
      else notify(`Could not open the enquiry: ${r.data?.error || r.message || "unknown"}`, { sticky: true });
    } catch (e: any) {
      notify(`Could not open the enquiry: ${e?.message || "the request failed"}`, { sticky: true });
    } finally { setBusy(null); }
  }, []);

  const setStatus = async (id: number, status: string, note = "") => {
    setBusy(status);
    try {
      const r = await callInbox("update_buyer_inquiry", { inquiry_id: id, status, note });
      if (r.data?.ok) {
        notify(`Enquiry marked ${status}.`);
        await load(0);
        if (selected === id) await open(id);
      } else notify(`Could not update: ${r.data?.error || "unknown"}`, { sticky: true });
    } finally { setBusy(null); }
  };

  const refreshOne = async (id: number) => {
    setBusy("refresh");
    try {
      const r = await callInbox("get_buyer_inquiry", { inquiry_id: id, refresh: 1 });
      if (r.data?.ok) { setDetail(r.data as BuyerInquiry); await load(0); notify("Re-read from the ERP."); }
    } finally { setBusy(null); }
  };

  const filtered = useMemo(() => {
    if (!filter) return rows;
    const f = filter.toLowerCase();
    return rows.filter((r) =>
      (r.buyer_name || "").toLowerCase().includes(f) ||
      (r.subject || "").toLowerCase().includes(f) ||
      (r.styles || []).join(" ").toLowerCase().includes(f) ||
      (r.status || "").toLowerCase().includes(f));
  }, [rows, filter]);

  return (
    <div className="inq">
      <div className="inq__head">
        <div>
          <h2 className="inq__title">Buyer enquiries</h2>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Every enquiry the intake has read, with what we already know about each style it names.
            A style we made before carries the price we last sold it at — the answer is on file.
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="btn btn--sm" disabled={!!busy} onClick={() => void load(1)}>
            {busy ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />} Re-read the ERP
          </button>
        </div>
      </div>

      {summary && (
        <div className="inq__kpis">
          <Kpi label="Enquiries" value={summary.total} />
          <Kpi label="New" value={summary.new} tone="warning" />
          <Kpi label="Quoted" value={summary.quoted} tone="positive" />
          <Kpi label="Won" value={summary.won} tone="positive" />
          <Kpi label="With old styles" value={summary.with_old_styles} />
          <Kpi label="Ready to quote" value={summary.quote_ready} tone="positive" />
          <Kpi label="Styles asked" value={summary.styles} />
        </div>
      )}

      <div className="inq__body">
        <div className="inq__list">
          <input className="input" placeholder="Search buyer, style, status…"
                 value={filter} onChange={(e) => setFilter(e.target.value)} />
          {loading && !rows.length && [0, 1, 2].map((i) => <Skel key={i} h={62} style={{ marginTop: 8 }} />)}
          {!loading && !filtered.length && (
            <Empty title="No enquiry yet"
                   hint="Read the mailbox in Order intake — every enquiry it finds lands here." />
          )}
          {filtered.map((r) => {
            const due = daysTo(r.quote_due);
            return (
              <button key={r.id} className={`inq__card${selected === r.id ? " is-active" : ""}`}
                      onClick={() => void open(r.id)}>
                <div className="inq__card-top">
                  <span className={`badge ${STATUS_BADGE[r.status] || "badge--outline"}`}>{r.status}</span>
                  {!!r.old_styles.length && (
                    <span className="badge badge--positive"><Tag size={10} /> {r.old_styles.length} old</span>
                  )}
                  {!!r.new_styles.length && (
                    <span className="badge badge--outline">{r.new_styles.length} new</span>
                  )}
                  {due !== null && (
                    <span className={`badge ${due < 0 ? "badge--critical" : due <= 7 ? "badge--warning" : "badge--outline"}`}>
                      quote {due < 0 ? `${Math.abs(due)}d late` : `in ${due}d`}
                    </span>
                  )}
                  {!!(r.stale && r.stale.length) && (
                    <span className="badge badge--critical" title={`deleted in the ERP: ${r.stale.join(", ")}`}>
                      deleted in ERP
                    </span>
                  )}
                </div>
                <div className="inq__card-buyer">{r.buyer_name || r.buyer_email}</div>
                <div className="inq__card-styles">{(r.styles || []).join(" · ") || "no style read"}</div>
                <div className="inq__card-foot">
                  <span>{r.total_qty ? `${fmtNum(r.total_qty)} pcs` : "qty not read"}</span>
                  <span>{r.received_at ? fmtDate(r.received_at) : ""}</span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="inq__detail">
          {busy === "open" && <div className="intake__reading"><Loader2 size={14} className="spin" /> Opening…</div>}
          {!detail && busy !== "open" && (
            <Empty title="Select an enquiry"
                   hint="Each row is one buyer asking for a price — open it to see what we already hold." />
          )}
          {detail && (
            <>
              <Card
                title={<span className="inq__dtitle">{detail.buyer_name || detail.buyer_email}</span>}
                sub={<span>
                  {detail.subject} · received {fmtDate(detail.received_at)}
                  {detail.customer ? ` · Customer ${detail.customer}` : " · buyer not in the ERP yet"}
                </span>}
                actions={
                  <>
                    <button className="btn btn--sm" disabled={!!busy}
                            onClick={() => void refreshOne(detail.id)}>
                      <RefreshCw size={13} /> Re-read history
                    </button>
                    {detail.run_id && onOpenIntake && (
                      <button className="btn btn--sm" onClick={() => onOpenIntake(detail.run_id!)}>
                        <ScanLine size={13} /> Open the mail
                      </button>
                    )}
                    {detail.status !== "quoted" && detail.status !== "won" && (
                      <button className="btn btn--sm btn--primary" disabled={!!busy}
                              onClick={() => void setStatus(detail.id, "quoted", "quotation issued")}>
                        <Check size={13} /> Mark quoted
                      </button>
                    )}
                    {detail.status !== "won" && (
                      <button className="btn btn--sm" disabled={!!busy}
                              onClick={() => void setStatus(detail.id, "won", "order received")}>
                        <CheckCircle2 size={13} /> Won
                      </button>
                    )}
                    {detail.status !== "lost" && (
                      <button className="btn btn--sm" disabled={!!busy}
                              onClick={() => void setStatus(detail.id, "lost", "no order")}>
                        <XCircle size={13} /> Lost
                      </button>
                    )}
                  </>
                }
              >
                <div className="dstrip">
                  <Cell k="Buyer" v={detail.buyer_name || "—"} />
                  <Cell k="Qty asked" v={detail.total_qty ? `${fmtNum(detail.total_qty)} pcs` : "—"} />
                  <Cell k="Styles" v={String((detail.styles || []).length)} />
                  <Cell k="Quote by" v={detail.quote_due ? fmtDate(detail.quote_due) : "—"}
                        tone={(() => { const d = daysTo(detail.quote_due); return d !== null && d < 0 ? "warn" : undefined; })()} />
                  <Cell k="Target ship" v={detail.target_ship ? fmtDate(detail.target_ship) : "—"} />
                  <Cell k="Opportunity" v={detail.opportunity || "—"} />
                  <Cell k="Currency" v={detail.currency || "—"} />
                </div>

                {detail.quote_due_note && (
                  <div className="dnote">
                    Quote-by date read {detail.quote_due ? fmtDate(detail.quote_due) : ""} — {detail.quote_due_note}.
                  </div>
                )}

                {!!(detail.asks || []).length && (
                  <div className="facts__group" style={{ marginTop: 10 }}>
                    <div className="facts__h">What they asked for</div>
                    {(detail.asks || []).map((a, i) => <div key={i} className="fact-ask">{a}</div>)}
                  </div>
                )}

                <div className="facts__h" style={{ marginTop: 14 }}>The styles, and what we already hold</div>
                <div className="inq__styles">
                  {(detail.lines || []).map((l) => (
                    <div key={l.style} className={`inq__style is-${l.verdict}`}>
                      <div className="inq__style-head">
                        <b>{l.style}</b>
                        {l.description ? <span className="muted"> {l.description}</span> : null}
                        <span className={`badge ${VERDICT[l.verdict]?.badge || "badge--outline"}`}>
                          {VERDICT[l.verdict]?.text || l.verdict}
                        </span>
                        {l.quote_ready && (
                          <span className="badge badge--positive">
                            <Sparkles size={10} /> price on file {money(l.last_price, l.currency)}
                          </span>
                        )}
                      </div>
                      <div className="inq__style-grid">
                        <Mini k="Last price" v={money(l.last_price, l.currency)} />
                        <Mini k="Orders" v={String(l.order_count ?? (l.orders || []).length)} />
                        <Mini k="Last order"
                              v={l.last_order ? `${l.last_order.sales_order} · ${fmtDate(l.last_order.date)}` : "—"} />
                        <Mini k="Cost sheet"
                              v={l.cost?.name ? `${l.cost.name} · ${money(l.cost.locked_fob || l.cost.total_fob, l.currency)}` : "—"} />
                        <Mini k="BOM" v={l.bom?.count ? `${l.bom.count} per size` : "none"} />
                        <Mini k="Tech pack"
                              v={l.tech_pack?.name ? `${l.tech_pack.name} · rev ${l.tech_pack.pack_revision || "—"}` : "none"} />
                        <Mini k="Item master"
                              v={l.item ? `${l.item}${(l.sizes || []).length ? ` · ${(l.sizes || []).join("/")}` : ""}` : "not on file"} />
                      </div>
                      {(l.errors || []).length > 0 && (
                        <div className="inq__warn">
                          <AlertTriangle size={12} /> could not read: {(l.errors || []).join(" · ")} — treat the blanks above as unknown, not as none
                        </div>
                      )}
                    </div>
                  ))}
                  {!(detail.lines || []).length && (
                    <div className="muted" style={{ fontSize: 12.5 }}>
                      No style could be read from this mail — open it and correct the style code.
                    </div>
                  )}
                </div>

                <div className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>
                  <FileText size={11} /> history read {detail.history_at ? fmtDate(detail.history_at) : "—"} from
                  Sales Order lines, Cost Sheet, Item Price, BOM and Buyer Tech Pack.
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={`inq__kpi${tone ? ` is-${tone}` : ""}`}>
      <div className="inq__kpi-v">{value ?? 0}</div>
      <div className="inq__kpi-l">{label}</div>
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

function Mini({ k, v }: { k: string; v: string }) {
  return (
    <div className="inq__mini">
      <div className="inq__mini-k">{k}</div>
      <div className="inq__mini-v">{v}</div>
    </div>
  );
}
