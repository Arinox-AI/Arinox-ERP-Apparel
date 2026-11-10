import { useState } from "react";
import { Check, ExternalLink } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Kpi, Loading, Note, Select, num, useCall, useToast } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";
import { useAct } from "./StepAct";
import { TrackStep } from "./TrackStep";

/* Step 9 of the Order page: ship (ORDER_TO_SHIP_PLAN section 4). The shipment wizard: pick the packing lists, create the Shipment, make the Delivery Notes
   (a manager approves), submit them, record the booking, bill of lading and tracking. Below the wizard sits what used to be the Deal page's "Ship & track":
   the four clocks, the papers the contract names and the trade term (`TrackStep`, backend `ship_track.py`). */

const MODES = ["Sea FCL", "Sea LCL", "Air", "Courier", "Road"];
const STAGES: [string, string][] = [["picked", "Lists picked"], ["dn_draft", "Delivery notes made"], ["dn_done", "Notes submitted"], ["on_board", "On board"]];
const ORDER = STAGES.map((x) => x[0]);
const BOOK: [string, string, string?][] = [["apparel_forwarder", "Forwarder"], ["apparel_booking_no", "Booking no"], ["apparel_booking_date", "Booking date", "date"], ["apparel_cutoff", "Cut-off", "date"],
  ["apparel_vessel_voyage", "Vessel / voyage"], ["apparel_etd", "ETD", "date"], ["apparel_eta", "ETA", "date"], ["apparel_on_board_date", "On board", "date"], ["apparel_hbl_no", "HBL no"], ["apparel_mbl_no", "MBL no"],
  ["carrier", "Carrier"], ["awb_number", "AWB / BL number"], ["tracking_url", "Tracking link"]];
const FIELD_OF: Record<string, string> = { apparel_forwarder: "forwarder", apparel_booking_no: "booking_no", apparel_booking_date: "booking_date", apparel_cutoff: "cutoff", apparel_vessel_voyage: "vessel_voyage",
  apparel_etd: "etd", apparel_eta: "eta", apparel_on_board_date: "on_board", apparel_hbl_no: "hbl", apparel_mbl_no: "mbl", carrier: "carrier", awb_number: "awb", tracking_url: "tracking_url" };

function ShipCard({ sh, w, act, onOpen }: { sh: R; w: boolean; act: ReturnType<typeof useAct>; onOpen: (dt: string, n: string) => void }) {
  const toast = useToast();
  const [ed, setEd] = useState<R>({});
  const at = ORDER.indexOf(sh.stage?.key);
  const dns: R[] = sh.delivery_notes || [];
  const save = () => {
    const v: R = {};
    for (const [k] of BOOK) if (ed[k] !== undefined && String(ed[k]) !== String(sh[FIELD_OF[k]] ?? "")) v[k] = ed[k];
    if (!Object.keys(v).length) { toast("Nothing changed."); return; }
    void act.ask("order_ship_record", { shipment: sh.name, values: v }, `Record the booking on ${sh.name}`);
  };
  return (
    <Card title={sh.name} sub={`${sh.mode || "—"} · ${(sh.packing_lists || []).join(", ")} · ${sh.docstatus === 1 ? "submitted" : "draft"}`}
      right={<><Badge tone={sh.stage?.key === "on_board" ? "ok" : "info"}>{STAGES.find((x) => x[0] === sh.stage?.key)?.[1]}</Badge><Btn sm kind="plain" onClick={() => onOpen("Shipment", sh.name)}><ExternalLink size={12} /> Open</Btn></>}>
      <ol className="ws-small" style={{ display: "flex", gap: 14, flexWrap: "wrap", listStyle: "none", padding: 0, margin: 0 }} aria-label="Shipment stages">
        {STAGES.map(([k, l], i) => <li key={k} style={{ fontWeight: i === at ? 700 : 400, opacity: i > at ? 0.5 : 1 }}>{i < at || sh.stage?.key === "on_board" ? <Check size={12} /> : `${i + 1}.`} {l}</li>)}
      </ol>
      <div className="ws-mt"><Note>{sh.stage?.next}</Note></div>
      <div className="ws-row ws-mt" style={{ flexWrap: "wrap", gap: 8 }}>
        {w && sh.can_make_dns && <Btn kind="primary" busy={act.busy} onClick={() => act.ask("order_ship_make_dns", { shipment: sh.name }, `Make the delivery notes of ${sh.name}`)}>Make delivery notes</Btn>}
        {w && dns.filter((d) => d.docstatus === 0).map((d) => <Btn key={d.name} onClick={() => act.ask("order_ship_submit", { doctype: "Delivery Note", name: d.name }, `Submit delivery note ${d.name}`)}>Submit {d.name}</Btn>)}
        {w && sh.can_submit && <Btn onClick={() => act.ask("order_ship_submit", { doctype: "Shipment", name: sh.name }, `Submit shipment ${sh.name}`)}>Submit the shipment</Btn>}
      </div>
      {dns.length > 0 && (
        <div className="ws-table-wrap ws-mt"><table className="ws-table" aria-label="Delivery notes"><thead><tr><th>Delivery note</th><th>Date</th><th>Status</th></tr></thead>
          <tbody>{dns.map((d) => <tr key={d.name} className="is-click" onClick={() => onOpen("Delivery Note", d.name)}><td><b className="ws-small">{d.name}</b></td><td className="ws-small">{String(d.posting_date || "").slice(0, 10)}</td>
            <td><Badge tone={d.docstatus === 1 ? "ok" : "warn"}>{d.docstatus === 1 ? "Submitted" : "Draft"}</Badge></td></tr>)}</tbody></table></div>)}
      {sh.freight?.rows?.length > 0 && <div className="ws-small ws-muted ws-mt">Freight {num(sh.freight.cost, 2)} shared by {sh.freight.basis}: {sh.freight.rows.map((r: any[]) => `${r[0]} ${num(r[2], 2)}`).join(" · ")}</div>}
      {w && (
        <details className="ws-mt" open={sh.stage?.key === "dn_done"}>
          <summary className="ws-small">Booking, bill of lading and tracking</summary>
          <div className="ws-form ws-mt">{BOOK.map(([k, l, t]) => <Field key={k} label={l} wide={k === "tracking_url"}><Input type={t} value={ed[k] ?? String(sh[FIELD_OF[k]] ?? "").slice(0, t === "date" ? 10 : 400)} onChange={(v) => setEd({ ...ed, [k]: v })} /></Field>)}</div>
          <div className="ws-row" style={{ justifyContent: "flex-end", marginTop: 8 }}><Btn kind="primary" onClick={save}>Save to the shipment</Btn></div>
        </details>)}
    </Card>
  );
}

export function Ship({ so, onChanged, go }: { so: string; onChanged: () => void; go: (p: string) => void }) {
  const cx = useCx();
  const toast = useToast();
  const r = useCall("order_ship_get", { sales_order: so }, []);
  const act = useAct(() => { onChanged(); void r.reload(true); });
  const [pick, setPick] = useState<string[]>([]);
  const [mode, setMode] = useState("Sea FCL");
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <Card title="Shipment wizard"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Shipment wizard"><Note tone="bad">{r.error || "Shipping could not be read."}</Note></Card>;
  const av: R[] = d.available || [], ships: R[] = d.shipments || [], s: R = d.summary || {};
  const w = !!d.can_write;
  const toggle = (n: string) => setPick((l) => (l.includes(n) ? l.filter((x) => x !== n) : [...l, n]));
  const tone = (a: R): Tone => (a.ready ? "ok" : "warn");
  const open = (dt: string, n: string) => cx?.openDoc?.(dt, n);

  return (
    <>
      <Card title="Shipment wizard" sub="1. Pick the packing lists. 2. Create the shipment. 3. Make and submit the delivery notes (a manager approves each). 4. Record the booking and the on-board date.">
        <div className="ws-grid ws-grid--kpi">
          <Kpi label="Lists waiting" value={num(s.waiting_lists)} /><Kpi label="Shipments" value={num(s.shipments)} /><Kpi label="Notes submitted" value={num(s.delivery_notes_submitted)} /><Kpi label="On board" value={num(s.on_board)} tone={s.on_board ? "ok" : undefined} />
        </div>
        {av.length === 0 ? <div className="ws-mt"><Empty title="No packing list is waiting" text="A packing list is ready for a shipment once it is submitted and not on another shipment." /></div> : (
          <div className="ws-table-wrap ws-mt"><table className="ws-table" aria-label="Packing lists waiting for a shipment"><thead><tr><th /><th>Packing list</th><th className="num">Cartons</th><th className="num">Pieces</th><th className="num">Gross kg</th><th className="num">CBM</th><th>Final inspection</th></tr></thead>
            <tbody>{av.map((a) => (
              <tr key={a.name}><td><input type="checkbox" aria-label={`Pick ${a.name}`} disabled={!w} checked={pick.includes(a.name)} onChange={() => toggle(a.name)} /></td>
                <td><b className="ws-small">{a.name}</b><div className="ws-small ws-muted">{a.customer}{a.ship_to ? ` · ${a.ship_to}` : ""}</div></td><td className="num">{num(a.total_cartons)}</td><td className="num">{num(a.total_pieces)}</td>
                <td className="num">{num(a.total_gross_kg, 1)}</td><td className="num">{num(a.total_cbm, 2)}</td><td><Badge tone={tone(a)}>{a.inspection_result || "not inspected"}</Badge></td></tr>))}</tbody></table></div>)}
        {w && av.length > 0 && (
          <div className="ws-row ws-mt" style={{ justifyContent: "flex-end", alignItems: "flex-end", gap: 10 }}>
            <Field label="Mode"><Select value={mode} onChange={setMode} options={MODES} /></Field>
            <Btn kind="primary" disabled={!pick.length} busy={act.busy} onClick={() => act.ask("order_shipment_create", { sales_order: so, packing_lists: pick, mode }, `Create a shipment of ${pick.length} packing list(s)`).then(() => setPick([]))}>Create shipment{pick.length ? ` (${pick.length})` : ""}</Btn>
          </div>)}
      </Card>
      {ships.map((sh) => <ShipCard key={sh.name} sh={sh} w={w} act={act} onOpen={open} />)}
      {d.deal_id
        ? <TrackStep deal={{ id: d.deal_id }} toast={toast} go={go} readOnlyGoods />
        : <Card title="Clocks and papers"><Note>This order was not made from a deal in the tower, so the contract's shipping clocks and papers are not tracked here. They appear when the order comes from a deal.</Note></Card>}
      {act.modal}
    </>
  );
}
