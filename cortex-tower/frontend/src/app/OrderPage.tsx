import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, ExternalLink, RefreshCw } from "lucide-react";
import { Badge, Btn, Card, Empty, Head, Loading, Note, day, money, num, useCall, when } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";
import { AllocationBoard } from "./AllocationBoard";
import { TnaPlan } from "./TnaPlan";
import { SamplesPP } from "./SamplesPP";
import { Materials } from "./Materials";
import { CutSew } from "./CutSew";
import { Subcontract } from "./Subcontract";
import { Pack } from "./Pack";
import { Ship } from "./Ship";
import { Invoice } from "./Invoice";

/* One Order page per Sales Order (ORDER_TO_SHIP_PLAN section 4): the same look and behaviour as the Deal page, with its own
   step bar. Slice S2 is READ ONLY: Status and Documents for every step. The Actions block of each step arrives with the
   slice that builds it (S3 allocation, S4 samples, ...). Everything shown comes from `order_get`; no ERP address is built
   here (the backend resolves every link through erp.url_for). */

const HINT: Record<string, string> = {
  confirm: "The Sales Order is confirmed when it is submitted in the ERP.",
  allocate: "Where to produce: factory and line for every style and colour, with the PCD.",
  tna: "The time and action plan for this order: one plan per style and colour.",
  samples: "Sample approvals, the pre-production meeting and the bulk gate.",
  materials: "Fabric and trim requisitions, purchase orders, receipts and inspections.",
  cutsew: "Production cards, cutting, sewing and the line reports.",
  subcontract: "Wash, print and embroidery out and back, then the finishing receipt.",
  pack: "Packing lists, cartons and the final inspection.",
  ship: "Shipment, delivery notes and the letter of credit.",
  invoice: "Invoices, payments, claims and the commercial close.",
};
const STATE_TONE: Record<string, Tone> = { done: "ok", doing: "info", blocked: "bad", todo: undefined, na: undefined };
const STATE_WORD: Record<string, string> = { done: "Done", doing: "In progress", blocked: "Blocked", todo: "To do", na: "Not needed" };

export function StateBadge({ state }: { state: string }) { return <Badge tone={STATE_TONE[state]}>{STATE_WORD[state] || state}</Badge>; }

export function OrderPage({ so, step: stepKey, go }: { so: string; step?: string; go: (p: string) => void }) {
  const r = useCall("order_get", { sales_order: so }, []);
  const [view, setView] = useState<string | null>(stepKey || null);
  const d: R | undefined = r.data || undefined;
  const steps: R[] = d?.steps || [];
  const nowKey: string = d?.next?.step && steps.some((s) => s.key === d.next.step) ? d.next.step : steps.find((s) => s.state !== "done")?.key || "confirm";
  useEffect(() => { setView(stepKey || null); }, [so, stepKey]);
  const shown = view || nowKey;
  const cur = useMemo(() => steps.find((s) => s.key === shown), [steps, shown]);
  if (r.loading && !d) return <div className="ws-page"><Loading rows={5} /></div>;
  if (!d) return <div className="ws-page"><Note tone="bad">{r.error || "Order not found."}</Note><div className="ws-mt"><Btn onClick={() => go("orders")}>Back to orders</Btn></div></div>;
  const h: R = d.header || {};
  const nowIdx = steps.findIndex((s) => s.key === nowKey);
  const rag = h.rag === "red" ? "bad" : h.rag === "amber" ? "warn" : h.rag === "green" ? "ok" : undefined;
  const late = h.days_to_ex_factory !== null && h.days_to_ex_factory !== undefined && h.days_to_ex_factory < 0;

  return (
    <div className="ws-page">
      <div className="ws-row" style={{ marginBottom: 10 }}>
        <Btn kind="plain" sm onClick={() => go("orders")}><ArrowLeft size={14} /> Orders</Btn>
        {h.contract && <span className="ws-small ws-muted">Contract {h.contract}</span>}
        <span style={{ marginLeft: "auto" }} />
        <Btn sm icon title="Refresh from the ERP" onClick={() => r.reload(true)}><RefreshCw size={14} /></Btn>
      </div>
      {r.error && <div className="ws-mb"><Note tone="warn">{r.error} Showing what was read last; changes are refused until the ERP answers.</Note></div>}
      {d.history && <div className="ws-mb"><Note tone="warn">{so} was amended. This page follows the live order <b>{d.head}</b>; documents of the earlier version are shown as history.
        {so !== d.head && <> <Btn kind="plain" sm onClick={() => go(`orders/${encodeURIComponent(d.head)}`)}>Open {d.head}</Btn></>}</Note></div>}

      <div className="ws-head" style={{ marginBottom: 14 }}>
        <div style={{ minWidth: 0 }}>
          <div className="ws-row"><Badge tone={rag}>{h.rag === "red" ? "Blocked" : h.rag === "amber" ? "Needs attention" : h.rag === "green" ? "On track" : "Not started"}</Badge><span className="ws-muted ws-small">{h.customer || "No customer"}</span></div>
          <h2 style={{ marginTop: 6 }}>{d.head}</h2>
        </div>
        <div className="ws-head__acts ws-order-kpis">
          <div className="ws-right"><div className="ws-small ws-muted">Styles</div><b className="ws-mono">{num(h.styles)}</b></div>
          <div className="ws-right"><div className="ws-small ws-muted">Quantity</div><b className="ws-mono">{num(h.qty)} pcs</b></div>
          <div className="ws-right"><div className="ws-small ws-muted">Value</div><b className="ws-mono">{h.value ? money(h.value, h.currency) : "—"}</b></div>
          <div className="ws-right"><div className="ws-small ws-muted">Ex-factory</div><b className="ws-mono">{day(h.ex_factory)}</b>
            {h.days_to_ex_factory !== null && h.days_to_ex_factory !== undefined && <div className="ws-small" style={{ color: late ? "var(--ws-bad)" : "var(--ws-muted)" }}>{late ? `${-h.days_to_ex_factory} days past` : `in ${h.days_to_ex_factory} days`}</div>}</div>
        </div>
      </div>

      <div className="ws-next" style={{ marginBottom: 12 }}>
        <ArrowRight size={18} />
        <div style={{ flex: 1 }}><b>{d.next?.text}</b></div>
        {shown !== nowKey && d.next?.step !== "done" && <Btn sm kind="ghost" onClick={() => setView(null)}>Go to this step</Btn>}
      </div>

      <TnaStrip steps={steps} onOpen={() => setView("tna")} />

      <div className="ws-steps" role="tablist" aria-label="Order steps">
        {steps.map((s, i) => (
          <button key={s.key} role="tab" aria-selected={s.key === shown}
            className={`ws-step${s.state === "done" ? " is-done" : ""}${i === nowIdx ? " is-now" : ""}${s.key === shown ? " is-view" : ""}${s.state === "blocked" ? " is-blocked" : ""}`} onClick={() => setView(s.key)}>
            <span className="ws-step__n">{s.state === "done" ? <Check size={12} /> : i + 1}</span>
            <span className="ws-step__l">{s.label}</span>
            <span className="ws-step__s">{STATE_WORD[s.state]}{s.counts?.total ? ` · ${s.counts.total}` : ""}</span>
          </button>))}
      </div>

      <div className="ws-grid ws-grid--side ws-mt">
        <div className="ws-stack">{cur && <StepView step={cur} page={d.by_step?.[cur.key]} so={d.head} confirmed={h.docstatus === 1} reload={() => r.reload(true)} go={go} />}</div>
        <OrderSide d={d} />
      </div>
    </div>
  );
}

/** One order's milestones as a single row, today marked, late ones red. Reads the T&A step's own TNA Milestone documents. */
function TnaStrip({ steps, onOpen }: { steps: R[]; onOpen: () => void }) {
  const ms: R[] = (steps.find((s) => s.key === "tna")?.docs || []).filter((x: R) => x.doctype === "TNA Milestone" && x.date && !x.history);
  if (!ms.length) return null;
  const t = (s: string) => new Date(s.slice(0, 10) + "T00:00:00").getTime();
  const dates = ms.map((m) => t(m.date)).filter((n) => !isNaN(n));
  const today = new Date(new Date().toDateString()).getTime();
  const lo = Math.min(...dates, today), hi = Math.max(...dates, today);
  const pos = (n: number) => (hi === lo ? 50 : ((n - lo) / (hi - lo)) * 100);
  const late = ms.filter((m) => m.status === "Late").length;
  return (
    <div className="ws-card ws-tnastrip" role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }} aria-label="T&A strip for this order">
      <div className="ws-small ws-muted" style={{ marginBottom: 6 }}>T&A: {ms.length} milestones{late ? <b style={{ color: "var(--ws-bad)" }}> · {late} late</b> : ""}</div>
      <div className="ws-tnastrip__bar">
        {ms.map((m) => <i key={m.name} title={`${m.name} · ${day(m.date)} · ${m.status}`} className={`is-${m.status === "Late" ? "late" : m.status === "Done" ? "done" : "open"}`} style={{ left: `${pos(t(m.date))}%` }} />)}
        <span className="ws-tnastrip__today" style={{ left: `${pos(today)}%` }} title="Today" />
      </div>
      <div className="ws-tnastrip__ends ws-small ws-muted"><span>{day(new Date(lo).toISOString())}</span><span>{day(new Date(hi).toISOString())}</span></div>
    </div>
  );
}

function StepView({ step, page, so, confirmed, reload, go }: { step: R; page?: R; so: string; confirmed: boolean; reload: () => void; go: (p: string) => void }) {
  const cx = useCx();
  const docs: R[] = step.docs || [];
  if (step.restricted) return <Card title={step.label}><Note>Your role does not see this step.</Note></Card>;
  const c = step.counts || {};
  return (
    <>
      <Card title={step.label} sub={HINT[step.key]} right={<>
        <StateBadge state={step.state} />
        {page?.url && <Btn sm title={page.url} onClick={() => window.open(page.url, "_blank", "noopener")}><ExternalLink size={13} /> {page.label}</Btn>}</>}>
        <div className="ws-row" style={{ gap: 18, flexWrap: "wrap" }}>
          <div><div className="ws-small ws-muted">Documents</div><b className="ws-mono">{num(c.total)}</b></div>
          <div><div className="ws-small ws-muted">Submitted</div><b className="ws-mono">{num(c.submitted)}</b></div>
          <div><div className="ws-small ws-muted">Draft</div><b className="ws-mono">{num(c.draft)}</b></div>
          {c.cancelled ? <div><div className="ws-small ws-muted">Cancelled</div><b className="ws-mono">{num(c.cancelled)}</b></div> : null}
        </div>
        {(step.blockers || []).length > 0
          ? <div className="ws-mt ws-stack">{step.blockers.map((b: string, i: number) => <Note key={i} tone={step.state === "blocked" ? "bad" : "warn"}>{b}</Note>)}</div>
          : step.state === "done" ? <div className="ws-mt"><Note tone="ok">This step is complete.</Note></div>
            : step.state === "todo" && step.next?.text ? <div className="ws-mt"><Note>{step.next.text}</Note></div> : null}
      </Card>
      {step.key === "allocate" && (confirmed ? <AllocationBoard so={so} onSaved={reload} /> : <Note>Submit the Sales Order in the ERP first. Production is planned once the order is confirmed.</Note>)}
      {step.key === "tna" && (confirmed ? <TnaPlan so={so} onChanged={reload} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      {step.key === "samples" && (confirmed ? <SamplesPP so={so} onChanged={reload} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      {step.key === "materials" && (confirmed ? <Materials so={so} onChanged={reload} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      {step.key === "cutsew" && (confirmed ? <CutSew so={so} onChanged={reload} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      {step.key === "subcontract" && (confirmed ? <Subcontract so={so} onChanged={reload} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      {step.key === "pack" && (confirmed ? <Pack so={so} onChanged={reload} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      {step.key === "ship" && (confirmed ? <Ship so={so} onChanged={reload} go={go} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      {step.key === "invoice" && (confirmed ? <Invoice so={so} onChanged={reload} /> : <Note>Submit the Sales Order in the ERP first.</Note>)}
      <Card title="Documents" sub="Click a row to read it here. The ERP link opens it in the ERP." flush>
        {docs.length === 0 ? <Empty title="Nothing here yet" text="The documents of this step appear as they are made, here or in the ERP." /> : (
          <div className="ws-table-wrap"><table className="ws-table">
            <thead><tr><th>Document</th><th>Style / colour</th><th>Status</th><th>Date</th><th /></tr></thead>
            <tbody>{docs.slice(0, 200).map((x) => (
              <tr key={x.doctype + x.name} className="is-click" onClick={() => cx?.openDoc?.(x.doctype, x.name)} style={x.history ? { opacity: 0.55 } : undefined}>
                <td><div className="ws-small ws-muted">{x.doctype}{x.history ? " (earlier version)" : ""}</div><b className="ws-small">{x.name}</b></td>
                <td className="ws-small">{[x.style, x.colour].filter(Boolean).join(" / ") || "—"}</td>
                <td><Badge tone={x.status === "Cancelled" ? "bad" : x.docstatus === 1 ? "ok" : undefined}>{x.status || "—"}</Badge></td>
                <td className="ws-small">{x.date ? day(x.date) : "—"}</td>
                <td>{x.url && <span title="Open in the ERP" onClick={(e) => { e.stopPropagation(); window.open(x.url, "_blank", "noopener"); }}
                  style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer", color: "var(--ws-accent, #2563eb)" }}><span className="ws-small">ERP</span><ExternalLink size={13} /></span>}</td>
              </tr>))}</tbody></table></div>)}
        {docs.length > 200 && <div className="ws-small ws-muted" style={{ padding: "8px 14px 12px" }}>Showing the first 200 of {docs.length}. The ERP link of the step lists them all.</div>}
      </Card>
    </>
  );
}

function OrderSide({ d }: { d: R }) {
  const cx = useCx();
  const groups: { label: string; docs: R[] }[] = (d.steps || []).map((s: R) => ({ label: s.label, docs: (s.docs || []).filter((x: R) => !x.history).slice(0, 12) })).filter((g: R) => g.docs.length);
  const tl: R[] = d.timeline || [];
  return (
    <div className="ws-stack">
      <Card title="In the ERP" flush right={d.by_step?.confirm?.url ? <Btn sm onClick={() => window.open(d.by_step.confirm.url, "_blank", "noopener")}><ExternalLink size={13} /> Open Sales Order</Btn> : undefined}>
        {groups.length === 0 ? <div className="ws-small ws-muted" style={{ padding: 14 }}>No follow-on documents yet.</div> : groups.map((g) => (
          <div key={g.label}>
            <div className="ws-small ws-muted" style={{ padding: "8px 14px 2px", fontWeight: 600 }}>{g.label}</div>
            {g.docs.map((x) => (
              <div key={x.doctype + x.name} className="ws-list-row" onClick={() => cx?.openDoc?.(x.doctype, x.name)}>
                <div style={{ minWidth: 0, flex: 1 }}><div className="ws-small ws-muted">{x.doctype}</div><b className="ws-small">{x.name}</b></div>
                {x.status && <span className="ws-small ws-muted">{x.status}</span>}
              </div>))}
          </div>))}
      </Card>
      <Card title="Timeline">
        <div className="ws-timeline">{tl.length === 0 ? <div className="ws-small ws-muted">No activity yet.</div> : tl.map((e, i) => (
          <div key={i} className={`ws-tl is-${e.kind}`}><i /><div><div>{e.text}</div><div className="ws-muted">{when(e.at)}{e.by ? ` · ${e.by}` : ""}</div></div></div>))}</div>
      </Card>
    </div>
  );
}

/** The order book: Sales Orders with one chip per step. Opens the Order page. */
export function OrderBook({ go }: { go: (p: string) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(true);
  const r = useCall("order_list", { q, open_only: open }, []);
  const rows: R[] = r.data?.orders || [];
  return (
    <div className="ws-page">
      <Head title="Order book" sub="Submitted Sales Orders with where each one stands. Open one to plan and follow it."
        acts={<><input className="ws-input" style={{ width: 220 }} placeholder="Order or customer" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find an order" />
          <Btn sm kind={open ? "dark" : "ghost"} onClick={() => setOpen(!open)}>{open ? "Open orders" : "All orders"}</Btn></>} />
      {r.error && <Note tone="bad">{r.error}</Note>}
      {r.data && r.data.erp_profile === "cortex_evidence" && <div className="ws-mb"><Note tone="warn">This ERP does not carry the Arinox layer, so the step chips are not available.</Note></div>}
      {r.loading && !r.data ? <Loading /> : rows.length === 0 ? <Empty title="No orders" text="Orders appear here once a Sales Order is submitted in the ERP." /> : (
        <Card flush><div className="ws-table-wrap"><table className="ws-table">
          <thead><tr><th>Order</th><th>Buyer</th><th>Delivery</th><th className="num">Value</th><th>Steps</th></tr></thead>
          <tbody>{rows.map((o) => (
            <tr key={o.name} className="is-click" onClick={() => go(`orders/${encodeURIComponent(o.name)}`)}>
              <td><b>{o.name}</b><div className="ws-small ws-muted">{o.status}</div></td>
              <td>{o.customer_name || o.customer}</td>
              <td>{day(o.delivery_date)}</td>
              <td className="num">{money(o.grand_total, o.currency)}</td>
              <td><div className="ws-stepchips">{(o.chips || []).map((c: R) => <span key={c.key} title={`${c.label}: ${STATE_WORD[c.state]}`} className={`ws-stepchip is-${c.state}`}>{c.label.split(" ")[0].replace(",", "")}</span>)}</div></td>
            </tr>))}</tbody></table></div></Card>)}
    </div>
  );
}
