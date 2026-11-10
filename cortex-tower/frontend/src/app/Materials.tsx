import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Loading, Modal, Note, Select, Textarea, call, num, useCall, useToast } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";
import { useAct } from "./StepAct";

/* Step 5 of the Order page: materials (ORDER_TO_SHIP_PLAN section 4). The material status table comes from the ERP's own Material Status report
   (`order_materials_get`): required / ordered / received / passed / short per requisition line, ETA against the PCD. Actions: propose the
   requisition lines from the Tech Pack and order, edit and save a draft, approve it, make purchase orders (a manager approves that), import a
   roll list into a draft receipt, make the inspection of a received row and submit it. The Purchase Receipt itself is made in the ERP. */

const TONE: Record<string, Tone> = { Accepted: "ok", Rejected: "bad", Short: "warn", "In House - QC Pending": "info", "In Transit": "info", Ordered: "info", Requested: undefined, "On Hold": "warn" };
const FAB = ["fabric_description", "fabric_item", "supplier", "gsm", "cuttable_width_cm", "consumption", "consumption_source", "garment_qty"];
const TRIM = ["trim_category", "description", "trim_item", "supplier", "qty_per_garment", "calc_basis", "garment_qty"];
const SOURCES = ["Mini Marker", "Bulk Marker", "Cost Sheet", "Tech Pack", "Manual"];
const BASIS = ["Per Garment", "Per Size", "Per Colour", "Per Carton", "By Length", "Fixed Qty"];

export function Materials({ so, onChanged }: { so: string; onChanged: () => void }) {
  const cx = useCx();
  const toast = useToast();
  const r = useCall("order_materials_get", { sales_order: so }, []);
  const act = useAct(() => { onChanged(); void r.reload(true); });
  const [ed, setEd] = useState<{ kind: string; items: R[]; name?: string } | null>(null);
  const [rolls, setRolls] = useState<{ rec: R; text: string; uom: string } | null>(null);
  const [busy, setBusy] = useState("");
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <Card title="Material status"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Material status"><Note tone="bad">{r.error || "The materials could not be read."}</Note></Card>;
  const rows: R[] = d.rows || [], reqs: R[] = d.requisitions || [], recs: R[] = d.receipts || [], s: R = d.summary || {};

  const propose = async (kind: string) => {
    setBusy(kind);
    const res = await call("order_req_lines", { sales_order: so, kind });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP could not propose lines.", "bad"); return; }
    if (!res.items.length) { toast("The ERP has no lines to propose: check the Tech Pack of the style.", "bad"); return; }
    setEd({ kind, items: res.items });
  };
  const makeItems = async () => {
    if (!ed) return;
    setBusy("items");
    const res = await call("order_items_create", { kind: ed.kind, items: ed.items, preview: false });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP refused it.", "bad"); return; }
    setEd({ ...ed, items: res.items }); toast(`Items made: ${(res.made || []).length}.`);
  };

  return (
    <>
      <Card title="Material status" sub="From the ERP's Material Status report. Passed means accepted by inspection; short is what is still needed."
        right={d.can_write ? <><Btn sm busy={busy === "fabric"} onClick={() => propose("fabric")}>Fabric requisition</Btn><Btn sm busy={busy === "trim"} onClick={() => propose("trim")}>Trim requisition</Btn></> : undefined}>
        {rows.length === 0 ? <Empty title="No approved requisition yet" text="Raise the fabric and trim requisitions and approve them; every line then appears here with its status." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Material status" style={{ minWidth: 900 }}>
            <thead><tr><th>Material</th><th>Style / colour</th><th className="num">Required</th><th className="num">Ordered</th><th className="num">Received</th><th className="num">Passed</th><th className="num">Short</th><th>Status</th><th>ETA vs PCD</th></tr></thead>
            <tbody>{rows.map((x, i) => (
              <tr key={i}><td><div className="ws-small ws-muted">{x.type === "FR" ? "Fabric" : "Trim"} · {x.requisition}</div><b className="ws-small">{x.item || "—"}</b></td>
                <td className="ws-small">{[x.style_no, x.colour].filter(Boolean).join(" / ") || "—"}</td>
                <td className="num">{num(x.required, 1)}</td><td className="num">{num(x.ordered, 1)}</td><td className="num">{num(x.received, 1)}</td><td className="num">{num(x.passed, 1)}</td>
                <td className="num"><b>{num(x.short, 1)}</b></td><td><Badge tone={TONE[x.status]}>{x.status}</Badge></td>
                <td className={`ws-small${x.late ? " ws-matcell-late" : ""}`}>{x.note || "—"}</td></tr>))}</tbody></table></div>)}
        <div className="ws-mt ws-stack">
          {rows.length > 0 && (s.all_in_house_before_pcd ? <Note tone="ok">All bulk material is passed and in house before the PCD.</Note>
            : <Note tone={s.late ? "bad" : "warn"}>{s.passed} of {s.lines} lines passed{s.late ? `; ${s.late} late against the PCD` : ""}; {num(s.short, 1)} still short.</Note>)}
          {(d.no_requisition || []).length > 0 && rows.length > 0 && <Note tone="warn">No requisition yet for: {d.no_requisition.join(", ")}.</Note>}
        </div>
      </Card>

      <Card title="Requisitions" sub="Draft, approve, order. Approving makes the Material Requests; ordering makes the Purchase Orders (a manager approves that step).">
        {reqs.length === 0 ? <div className="ws-small ws-muted">None yet. Use the buttons above to propose the lines from the Tech Pack.</div> : (
          <div className="ws-stack">{reqs.map((q) => (
            <div key={q.name} className="ws-row" style={{ flexWrap: "wrap", gap: 8 }}>
              <b className="ws-small">{q.kind === "fabric" ? "Fabric" : "Trim"} {q.name}</b><Badge tone={q.docstatus === 1 ? "ok" : "warn"}>{q.status}</Badge>
              {d.can_write && q.docstatus === 0 && <Btn sm onClick={() => act.ask("order_req_approve", { kind: q.kind, name: q.name }, `Approve ${q.name}`)}>Approve</Btn>}
              {d.can_write && q.can_order && <Btn sm kind="primary" onClick={() => act.ask("order_po_make", { kind: q.kind, name: q.name }, `Make purchase orders from ${q.name}`)}>Make purchase orders</Btn>}
              <Btn sm kind="plain" onClick={() => cx?.openDoc?.(q.kind === "fabric" ? "Fabric Requisition" : "Trim Requisition", q.name)}><ExternalLink size={12} /> Open</Btn>
            </div>))}</div>)}
      </Card>

      <Card title="Receipts and inspection" sub="The Purchase Receipt is made in the ERP (it posts stock). Here: the roll list of a draft receipt, then the inspection of a received row." flush>
        {recs.length === 0 ? <Empty title="No receipt yet" text="Receive the purchase orders in the ERP; the received rows appear here." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Receipts"><thead><tr><th>Receipt</th><th>Material</th><th className="num">Qty</th><th>Inspection</th><th /></tr></thead>
            <tbody>{recs.map((x) => (
              <tr key={x.row_name}><td><b className="ws-small">{x.purchase_receipt}</b><div className="ws-small ws-muted">{x.docstatus === 1 ? "received" : "draft"} · {x.supplier}</div></td><td className="ws-small">{x.item}</td><td className="num">{num(x.qty, 1)}</td>
                <td>{x.inspection ? <><Badge tone={x.inspection.docstatus === 1 ? (x.inspection.result === "Pass" ? "ok" : "bad") : "warn"}>{x.inspection.docstatus === 1 ? (x.inspection.result || "Submitted") : "Draft"}</Badge> <span className="ws-small ws-muted">{x.inspection.name}</span></> : <span className="ws-muted">—</span>}</td>
                <td style={{ whiteSpace: "nowrap" }}>{d.can_write && <>
                  {x.can_import_rolls && <Btn sm onClick={() => setRolls({ rec: x, text: "", uom: "Meter" })}>Import rolls</Btn>}
                  {x.can_inspect && <Btn sm onClick={() => act.ask("order_inspection_make", { kind: x.kind, purchase_receipt: x.purchase_receipt, purchase_receipt_item: x.row_name }, "Make the inspection")}>Make inspection</Btn>}
                  {x.inspection && x.inspection.docstatus === 0 && <Btn sm kind="primary" onClick={() => act.ask("order_inspection_submit", { kind: x.inspection.kind, name: x.inspection.name }, `Submit ${x.inspection.name}`)}>Submit inspection</Btn>}</>}
                  <Btn sm kind="plain" onClick={() => cx?.openDoc?.("Purchase Receipt", x.purchase_receipt)}><ExternalLink size={12} /> Open</Btn></td></tr>))}</tbody></table></div>)}
      </Card>

      {ed && (
        <Modal wide title={`${ed.kind === "fabric" ? "Fabric" : "Trim"} requisition: draft`} sub="Lines proposed by the ERP from the Tech Pack and the order. Fill what is missing, make the items, then preview and save. Rows without a quantity are never sent." onClose={() => setEd(null)}
          foot={<><Btn onClick={() => setEd(null)}>Close</Btn><Btn busy={busy === "items"} onClick={makeItems}>Make missing items</Btn>
            <Btn kind="primary" busy={act.busy} onClick={() => { const p = { sales_order: so, kind: ed.kind, items: ed.items }; setEd(null); void act.ask("order_req_save", p, "Save the draft requisition"); }}>Preview and save</Btn></>}>
          <div className="ws-table-wrap"><table className="ws-table ws-table--edit" aria-label="Requisition lines" style={{ minWidth: 900 }}>
            <thead><tr><th>Style / colour</th>{(ed.kind === "fabric" ? FAB : TRIM).map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
            <tbody>{ed.items.map((it, i) => (
              <tr key={i}><td className="ws-small">{it.style_no || it.style_item}<div className="ws-muted">{it.colour}</div></td>
                {(ed.kind === "fabric" ? FAB : TRIM).map((c) => (
                  <td key={c}>{c === "consumption_source" ? <Select sm value={it[c]} placeholder="—" options={SOURCES} onChange={(v) => setEd({ ...ed, items: ed.items.map((x, k) => (k === i ? { ...x, [c]: v } : x)) })} />
                    : c === "calc_basis" ? <Select sm value={it[c]} options={BASIS} onChange={(v) => setEd({ ...ed, items: ed.items.map((x, k) => (k === i ? { ...x, [c]: v } : x)) })} />
                      : <Input sm value={it[c]} num={["gsm", "cuttable_width_cm", "consumption", "garment_qty", "qty_per_garment"].includes(c)} onChange={(v) => setEd({ ...ed, items: ed.items.map((x, k) => (k === i ? { ...x, [c]: v } : x)) })} aria-label={c} />}</td>))}</tr>))}</tbody></table></div>
        </Modal>)}
      {rolls && (
        <Modal title={`Roll list for ${rolls.rec.purchase_receipt}`} sub="One roll per line: roll number, dye lot, length. The total must equal the receipt row quantity." onClose={() => setRolls(null)}
          foot={<><Btn onClick={() => setRolls(null)}>Cancel</Btn><Btn kind="primary" onClick={() => { const p = { purchase_receipt: rolls.rec.purchase_receipt, row_name: rolls.rec.row_name, rolls: rolls.text, length_uom: rolls.uom }; setRolls(null); void act.ask("order_rolls_import", p, "Import the roll list"); }}>Preview</Btn></>}>
          <Field label="Length unit"><Select value={rolls.uom} onChange={(v) => setRolls({ ...rolls, uom: v })} options={["Meter", "Yard", "Kg"]} /></Field>
          <Field label="Rolls" wide><Textarea rows={8} value={rolls.text} placeholder={"R01, L1, 88.2\nR02, L1, 88.2"} onChange={(v) => setRolls({ ...rolls, text: v })} /></Field>
        </Modal>)}
      {act.modal}
    </>
  );
}
