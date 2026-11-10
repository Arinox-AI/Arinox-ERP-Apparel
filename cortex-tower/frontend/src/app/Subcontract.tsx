import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Kpi, Loading, Modal, Note, Textarea, call, money, num, useCall, useToast } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";
import { useAct } from "./StepAct";

/* Step 7 of the Order page: subcontract and finish (ORDER_TO_SHIP_PLAN section 4). The out / back balance per process (wash, print, embroidery) is the
   production ledger set against the challans. Actions: challan, return, settlement and finishing receipt in the generic form (pre-filled); short-close a
   challan (Production Manager, approval); make the vendor's invoices from a submitted settlement (approval; Accounts submits them). */

const TONE: Record<string, Tone> = { Open: "warn", "Partly Returned": "warn", Returned: "ok", "Short Closed": "bad", Closed: "ok" };

export function Subcontract({ so, onChanged }: { so: string; onChanged: () => void }) {
  const cx = useCx();
  const toast = useToast();
  const r = useCall("order_subcontract_get", { sales_order: so }, []);
  const act = useAct(() => { onChanged(); void r.reload(true); });
  const [reason, setReason] = useState<{ name: string; text: string } | null>(null);
  const [busy, setBusy] = useState("");
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <Card title="Out and back"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Out and back"><Note tone="bad">{r.error || "Subcontract could not be read."}</Note></Card>;
  const bal: R[] = d.balance || [], chs: R[] = d.challans || [], sets: R[] = d.settlements || [], fin: R[] = d.finishing || [], s: R = d.summary || {};
  const w = !!d.can_write;
  const fill = async (kind: string, extra: R = {}) => {
    setBusy(kind + (extra.challan || ""));
    const res = await call("order_prefill_sub", { sales_order: so, kind, ...extra });
    setBusy("");
    if (!res.ok) { toast(res.error || "Could not pre-fill the form.", "bad"); return; }
    if (res.note) toast(res.note);
    cx?.newDoc?.(res.doctype, res.initial);
  };

  return (
    <>
      <Card title="Out and back" sub="Per process: what was sent, what came back, what the vendor spoiled, what was short-closed and what is still out."
        right={w ? <Btn sm kind="primary" busy={busy === "challan"} onClick={() => fill("challan")}>New challan</Btn> : undefined}>
        {bal.length === 0 ? <Empty title="Nothing sent out" text="Make a challan when sewn pieces go to wash, print or embroidery. If nothing goes out, go to the finishing receipt." /> : (
          <>
            <div className="ws-grid ws-grid--kpi">
              <Kpi label="Sent" value={num(s.sent)} /><Kpi label="Back" value={num(s.back)} /><Kpi label="Short-closed" value={num(s.short_closed)} tone={s.short_closed ? "warn" : undefined} />
              <Kpi label="Still out" value={num(s.out_now)} tone={s.out_now ? "bad" : "ok"} />
            </div>
            <div className="ws-table-wrap ws-mt"><table className="ws-table" aria-label="Out and back per process">
              <thead><tr><th>Process</th><th className="num">Sent</th><th className="num">Back good</th><th className="num">Vendor rejects</th><th className="num">Factory rejects</th><th className="num">Short-closed</th><th className="num">Still out</th></tr></thead>
              <tbody>{bal.map((b) => (
                <tr key={b.process}><td><b className="ws-small">{b.process || "—"}</b><div className="ws-small ws-muted">{b.challans} challan(s){b.open_challans ? `, ${b.open_challans} open` : ""}</div></td>
                  <td className="num">{num(b.sent)}</td><td className="num">{num(b.good)}</td><td className="num">{num(b.reject_vendor)}</td><td className="num">{num(b.reject_factory)}</td>
                  <td className="num">{num(b.short_closed)}</td><td className="num"><b className={b.balance ? "ws-matcell-late" : undefined}>{num(b.balance)}</b></td></tr>))}</tbody></table></div>
            <div className="ws-mt">{s.nothing_out ? <Note tone="ok">Nothing is out at a subcontractor.</Note> : <Note tone="warn">{num(s.out_now)} pieces are still at a subcontractor.</Note>}</div>
          </>)}
      </Card>

      <Card title="Challans" sub="Receive the goods back with a return, short-close what will not come, then settle." flush>
        {chs.length === 0 ? <Empty title="No challan" /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Challans"><thead><tr><th>Challan</th><th>Process / vendor</th><th className="num">Sent</th><th className="num">Back</th><th className="num">Left</th><th>Status</th><th /></tr></thead>
            <tbody>{chs.map((c) => (
              <tr key={c.name}><td><b className="ws-small">{c.name}</b><div className="ws-small ws-muted">{c.docstatus === 1 ? "submitted" : "draft"}{c.short_close_reason ? ` · ${c.short_close_reason}` : ""}</div></td>
                <td className="ws-small">{c.subcontract_process}<div className="ws-muted">{c.supplier}</div></td><td className="num">{num(c.total_qty)}</td><td className="num">{num(c.returned_qty)}</td><td className="num">{num(c.left)}</td>
                <td><Badge tone={TONE[c.status]}>{c.status || "Draft"}</Badge></td>
                <td style={{ whiteSpace: "nowrap" }}>{w && <>
                  {c.can_return && <Btn sm busy={busy === "return" + c.name} onClick={() => fill("return", { challan: c.name })}>Return</Btn>}
                  {c.can_short_close && <Btn sm onClick={() => setReason({ name: c.name, text: "" })}>Short-close</Btn>}
                  {c.can_settle && <Btn sm kind="primary" busy={busy === "settlement" + c.name} onClick={() => fill("settlement", { challan: c.name })}>Settle</Btn>}</>}
                  <Btn sm kind="plain" onClick={() => cx?.openDoc?.("Subcontract Challan", c.name)}><ExternalLink size={12} /> Open</Btn></td></tr>))}</tbody></table></div>)}
      </Card>

      <Card title="Settlements" sub="The ERP works out what the vendor is owed: spoiled and missing pieces are not paid and damage above the limit costs a penalty. Invoices are drafted here and submitted by Accounts." flush>
        {sets.length === 0 ? <Empty title="No settlement yet" text="Settle a challan once its goods are back or it is short-closed." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Settlements"><thead><tr><th>Settlement</th><th className="num">Sent</th><th className="num">Good</th><th className="num">Short</th><th className="num">Payable</th><th className="num">Penalty</th><th className="num">Net</th><th>Invoices</th><th /></tr></thead>
            <tbody>{sets.map((x) => (
              <tr key={x.name}><td><b className="ws-small">{x.name}</b><div className="ws-small ws-muted">{x.challan} · {x.docstatus === 1 ? "submitted" : "draft"}</div></td>
                <td className="num">{num(x.sent_qty)}</td><td className="num">{num(x.good_qty)}</td><td className="num">{num(x.short_qty)}</td><td className="num">{num(x.payable_qty)}</td>
                <td className="num">{money(x.penalty_amount)}</td><td className="num">{money(x.net_amount)}</td>
                <td className="ws-small">{x.purchase_invoice || "—"}{x.debit_note ? ` · ${x.debit_note}` : ""}</td>
                <td style={{ whiteSpace: "nowrap" }}>{w && x.can_invoice && <Btn sm kind="primary" onClick={() => act.ask("order_settlement_invoices", { name: x.name }, `Draft the invoices of ${x.name}`)}>Make invoices</Btn>}
                  <Btn sm kind="plain" onClick={() => cx?.openDoc?.("Subcontract Settlement", x.name)}><ExternalLink size={12} /> Open</Btn></td></tr>))}</tbody></table></div>)}
      </Card>

      <Card title="Finishing receipt" sub="What arrives in finishing from sewing or back from a vendor. Submitting posts the ledger (a manager approves that)."
        right={w ? <Btn sm kind="primary" busy={busy === "finishing"} onClick={() => fill("finishing")}>New finishing receipt</Btn> : undefined} flush>
        {fin.length === 0 ? <Empty title="No finishing receipt yet" /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Finishing receipts"><thead><tr><th>Receipt</th><th>Date</th><th>Source</th><th className="num">Pieces</th><th>Status</th></tr></thead>
            <tbody>{fin.map((f) => (
              <tr key={f.name} className="is-click" onClick={() => cx?.openDoc?.("Finishing Receipt", f.name)}><td><b className="ws-small">{f.name}</b></td><td className="ws-small">{String(f.receipt_date || "")}</td><td className="ws-small">{f.source}</td>
                <td className="num">{num(f.total_qty)}</td><td><Badge tone={f.docstatus === 1 ? "ok" : "warn"}>{f.docstatus === 1 ? "Submitted" : "Draft"}</Badge></td></tr>))}</tbody></table></div>)}
      </Card>

      {reason && (
        <Modal title={`Short-close ${reason.name}`} sub="The rest will not come back; the gap shows as Short on the settlement. Production Manager only; a manager approves it." onClose={() => setReason(null)}
          foot={<><Btn onClick={() => setReason(null)}>Cancel</Btn><Btn kind="primary" disabled={!reason.text.trim()} onClick={() => { const p = { name: reason.name, reason: reason.text }; setReason(null); void act.ask("order_challan_short_close", p, `Short-close ${p.name}`); }}>Preview</Btn></>}>
          <Field label="Reason" wide><Textarea rows={4} value={reason.text} onChange={(v) => setReason({ ...reason, text: v })} /></Field>
        </Modal>)}
      {act.modal}
    </>
  );
}
