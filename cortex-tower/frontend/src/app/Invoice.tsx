import { useState } from "react";
import { Check, ExternalLink, X } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Kpi, Loading, Modal, Note, Textarea, money, num, useCall, useToast } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";
import { useAct } from "./StepAct";

/* Step 10 of the Order page: invoice, collect and close (ORDER_TO_SHIP_PLAN section 4). Prepare (drafts) and submit (a manager approves) the commercial invoices
   of a shipment: one invoice may list several contracts and is never split here. The receivable card shows each invoice's due date, days overdue and the buyer's
   promise, with a follow-up log. An accepted buyer claim gets its credit note drafted. The close checklist is the ERP's own; the claim windows may be waived
   with a reason; closing is a manager's approval. */

const TONE: Record<string, Tone> = { Paid: "ok", "Not Due": undefined, "Due Soon": "warn", "Partly Paid": "info", Promised: "warn", Overdue: "bad", Disputed: "bad", Draft: "warn" };

export function Invoice({ so, onChanged }: { so: string; onChanged: () => void }) {
  const cx = useCx();
  const toast = useToast();
  const r = useCall("order_invoice_get", { sales_order: so }, []);
  const act = useAct(() => { onChanged(); void r.reload(true); });
  const [fu, setFu] = useState<{ inv: R; f: R } | null>(null);
  const [waive, setWaive] = useState("");
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <Card title="Receivable"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Receivable"><Note tone="bad">{r.error || "Invoices could not be read."}</Note></Card>;
  const invs: R[] = d.invoices || [], t: R = d.totals || {}, pay: R[] = d.payments || [], claims: R[] = d.claims || [], ships: R[] = d.shipments || [], chk: R[] = d.checklist || [], cl: R = d.close || {}, s: R = d.summary || {};
  const w = !!d.can_write;
  const money0 = (v: any) => money(v, invs[0]?.currency || "USD");
  const sendFu = () => {
    if (!fu) return;
    const f = fu.f, p: R = { invoice: fu.inv.name, note: f.note };
    if (f.promise_date) { p.promise_date = f.promise_date; p.promise_amount = Number(f.promise_amount) || 0; }
    if (f.next_action_date) p.next_action_date = f.next_action_date;
    if (f.dispute !== undefined && f.dispute !== (fu.inv.apparel_dispute_reason || "")) p.dispute_reason = f.dispute;
    setFu(null);
    void act.ask("order_followup_log", p, `Log the follow-up on ${p.invoice}`);
  };

  return (
    <>
      <Card title="Receivable" sub="Each customer invoice with its due date, how many days overdue it is and what the buyer promised.">
        {invs.length === 0 ? <Empty title="No invoice yet" text="Once the delivery notes of a shipment are submitted, prepare its invoices below." /> : (
          <>
            <div className="ws-grid ws-grid--kpi">
              <Kpi label="Invoiced" value={money0(t.invoiced)} /><Kpi label="Credited" value={money0(t.credited)} /><Kpi label="Outstanding" value={money0(t.outstanding)} tone={t.outstanding ? "warn" : "ok"} />
              <Kpi label="Overdue" value={money0(t.overdue)} hint={t.oldest_days ? `oldest ${t.oldest_days} days` : undefined} tone={t.overdue ? "bad" : "ok"} />
            </div>
            <div className="ws-table-wrap ws-mt"><table className="ws-table" aria-label="Receivable"><thead><tr><th>Invoice</th><th>Due</th><th className="num">Days overdue</th><th className="num">Total</th><th className="num">Outstanding</th><th>State</th><th>Promise / next</th><th /></tr></thead>
              <tbody>{invs.map((i) => (
                <tr key={i.name}><td><b className="ws-small">{i.apparel_commercial_invoice_no || i.name}</b><div className="ws-small ws-muted">{i.name}{i.is_return ? " · credit note" : ""}{i.apparel_route_leg ? ` · leg ${i.apparel_route_leg}` : ""}</div>
                  {i.multi_contract && <div className="ws-small ws-muted">covers {i.contracts.join(", ")}</div>}</td>
                  <td className="ws-small">{i.due ? String(i.due) : "—"}</td><td className="num"><b className={i.days_overdue ? "ws-matcell-late" : undefined}>{num(i.days_overdue)}</b></td>
                  <td className="num">{money(i.grand_total, i.currency)}</td><td className="num">{money(i.outstanding, i.currency)}</td><td><Badge tone={TONE[i.state]}>{i.state}</Badge></td>
                  <td className="ws-small">{i.apparel_promise_date ? `${money(i.apparel_promise_amount, i.currency)} by ${String(i.apparel_promise_date).slice(0, 10)}` : "—"}{i.apparel_next_action_date ? <div className="ws-muted">next {String(i.apparel_next_action_date).slice(0, 10)}</div> : null}
                    {i.apparel_dispute_reason ? <div className="ws-muted">disputed: {i.apparel_dispute_reason}</div> : null}
                    {(i.log || []).slice(0, 3).map((l: R, k: number) => <div key={k} className="ws-muted" title={l.by}>{l.at.slice(0, 10)}: {l.text}</div>)}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{w && i.can_follow_up && <Btn sm onClick={() => setFu({ inv: i, f: { note: "", promise_date: "", promise_amount: String(i.outstanding || ""), next_action_date: "", dispute: i.apparel_dispute_reason || "" } })}>Follow up</Btn>}
                    <Btn sm kind="plain" onClick={() => cx?.openDoc?.("Sales Invoice", i.name)}><ExternalLink size={12} /> Open</Btn></td></tr>))}</tbody></table></div>
            {pay.length > 0 && <div className="ws-small ws-muted ws-mt">Payments: {pay.map((p) => `${p.name} (${num(p.allocated, 2)} on ${p.invoice}, ${p.date})`).join(" · ")}</div>}
          </>)}
      </Card>

      <Card title="Invoice a shipment" sub="One invoice per contract per shipment (a group customer gets two legs). Re-preparing replaces the drafts and keeps their numbers; submitted invoices are left alone." flush>
        {ships.length === 0 ? <Empty title="No shipment yet" text="Ship first (step 9)." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Shipments to invoice"><thead><tr><th>Shipment</th><th className="num">Notes</th><th>On board</th><th>Drafts</th><th>Submitted</th><th /></tr></thead>
            <tbody>{ships.map((x) => (
              <tr key={x.name}><td><b className="ws-small">{x.name}</b></td><td className="num">{x.dn_submitted} / {x.delivery_notes}</td><td className="ws-small">{x.on_board_date || "—"}</td>
                <td className="ws-small">{(x.drafts || []).join(", ") || "—"}</td><td className="ws-small">{(x.submitted || []).join(", ") || "—"}</td>
                <td style={{ whiteSpace: "nowrap" }}>{w && x.can_prepare && <Btn sm kind="primary" onClick={() => act.ask("order_invoice_prepare", { shipment: x.name }, `Prepare the invoices of ${x.name}`)}>Prepare invoices</Btn>}
                  {w && x.can_submit && <Btn sm kind="primary" onClick={() => act.ask("order_invoice_submit", { shipment: x.name }, `Submit the invoices of ${x.name}`)}>Submit invoices</Btn>}
                  {w && x.can_submit && <Btn sm onClick={() => act.ask("order_invoice_prepare", { shipment: x.name }, `Prepare the invoices of ${x.name} again`)}>Prepare again</Btn>}</td></tr>))}</tbody></table></div>)}
      </Card>

      <Card title="Buyer claims" sub="An accepted claim settled by credit note gets its credit note drafted here; the accountant submits it." flush>
        {claims.length === 0 ? <Empty title="No claim" /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Buyer claims"><thead><tr><th>Claim</th><th>Type</th><th className="num">Claimed</th><th className="num">Accepted</th><th>Settlement</th><th /></tr></thead>
            <tbody>{claims.map((c) => (
              <tr key={c.name}><td><b className="ws-small">{c.name}</b><div className="ws-small ws-muted">{c.status}{c.sales_invoice ? ` · on ${c.sales_invoice}` : ""}</div></td><td className="ws-small">{c.claim_type}</td><td className="num">{money0(c.claimed_amount)}</td><td className="num">{money0(c.accepted_amount)}</td>
                <td className="ws-small">{c.settlement || "—"}{c.credit_note ? ` · ${c.credit_note}` : ""}</td>
                <td style={{ whiteSpace: "nowrap" }}>{w && c.can_credit_note && <Btn sm kind="primary" onClick={() => act.ask("order_claim_credit_note", { claim: c.name }, `Draft the credit note of ${c.name}`)}>Make credit note</Btn>}
                  <Btn sm kind="plain" onClick={() => cx?.openDoc?.("Buyer Claim", c.name)}><ExternalLink size={12} /> Open</Btn></td></tr>))}</tbody></table></div>)}
      </Card>

      <Card title="Close checklist" sub="The ERP's own checklist. The order closes commercially when every row is green; only the claim windows may be waived, with a reason."
        right={<Badge tone={s.closed ? "ok" : cl.all_ok ? "ok" : "warn"}>{s.closed ? "Closed" : cl.all_ok ? "Ready to close" : "Not ready"}</Badge>}>
        {d.checklist_error && <Note tone="warn">{d.checklist_error}</Note>}
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }} aria-label="Close checklist">
          {chk.map((c, i) => <li key={i} className="ws-row" style={{ gap: 8, padding: "4px 0" }}>{c.ok ? <Check size={14} color="var(--ws-ok, #027a48)" /> : <X size={14} color="var(--ws-bad, #b42318)" />}<span><b className="ws-small">{c.label}</b>{c.detail ? <span className="ws-small ws-muted"> · {c.detail}</span> : null}</span></li>)}
        </ul>
        {!s.closed && w && (
          <div className="ws-mt">
            {cl.windows_open && <Field label="Why may it close while a claim window is open?" wide><Textarea rows={2} value={waive} onChange={setWaive} /></Field>}
            <div className="ws-row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
              <Btn kind="primary" disabled={!cl.can_close || (cl.windows_open && !waive.trim())} onClick={() => act.ask("order_close", { sales_order: so, waive_reason: waive }, "Close the order commercially")}>Close the order</Btn></div>
            {!cl.can_close && <div className="ws-mt"><Note>{(cl.hard || []).map((h: R) => h.label).join("; ")} must be done first.</Note></div>}
          </div>)}
        {s.closed && <div className="ws-mt"><Note tone="ok">This order is commercially closed.</Note></div>}
      </Card>

      {fu && (
        <Modal title={`Follow up ${fu.inv.name}`} sub={`${money(fu.inv.outstanding, fu.inv.currency)} outstanding${fu.inv.days_overdue ? `, ${fu.inv.days_overdue} days overdue` : ""}. Say what was said or agreed.`} onClose={() => setFu(null)}
          foot={<><Btn onClick={() => setFu(null)}>Cancel</Btn><Btn kind="primary" disabled={!fu.f.note.trim() || (!!fu.f.promise_date && !(Number(fu.f.promise_amount) > 0))} onClick={sendFu}>Preview</Btn></>}>
          <Field label="Note" wide><Textarea rows={3} value={fu.f.note} onChange={(v) => setFu({ ...fu, f: { ...fu.f, note: v } })} /></Field>
          <div className="ws-form">
            <Field label="Buyer promised to pay by"><Input type="date" value={fu.f.promise_date} onChange={(v) => setFu({ ...fu, f: { ...fu.f, promise_date: v } })} /></Field>
            <Field label="Promised amount"><Input type="number" value={fu.f.promise_amount} onChange={(v) => setFu({ ...fu, f: { ...fu.f, promise_amount: v } })} /></Field>
            <Field label="Next action on"><Input type="date" value={fu.f.next_action_date} onChange={(v) => setFu({ ...fu, f: { ...fu.f, next_action_date: v } })} /></Field>
            <Field label="Dispute reason (empty = none)" wide><Input value={fu.f.dispute} onChange={(v) => setFu({ ...fu, f: { ...fu.f, dispute: v } })} /></Field>
          </div>
        </Modal>)}
      {act.modal}
    </>
  );
}
