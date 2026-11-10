import { useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Kpi, Loading, Note, Select, call, num, useCall, useToast } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";

/* Step 8 of the Order page: pack and inspect (ORDER_TO_SHIP_PLAN section 4). The carton plan is the ERP's own generator (`arinox_packing_list_generate_cartons`)
   worked out without writing, set against the order per colour and size; the packing list, the final inspection (cartons drawn at random by the ERP, AQL result)
   and the needle detector log are made in the generic form, pre-filled. Submitting a packing list posts the ledger (a manager approves that). */

const PACK_TYPES = ["Solid Colour Solid Size", "Solid Colour Assorted Size", "Assorted"];
const TAIL = ["Mixed Colour and Size", "Mixed Size Only", "Own Carton"];
const RES_TONE: Record<string, Tone> = { Accepted: "ok", "Accepted with Concession": "warn", Rejected: "bad", "On Hold": "warn" };

export function Pack({ so, onChanged }: { so: string; onChanged: () => void }) {
  const cx = useCx();
  const toast = useToast();
  const r = useCall("order_pack_get", { sales_order: so }, []);
  const [card, setCard] = useState("");
  const [f, setF] = useState<R>({ pack_type: "Solid Colour Solid Size", pcs_per_carton: "24", tail_carton_rule: "Mixed Colour and Size", carton_start: "1" });
  const [ratio, setRatio] = useState<R>({});
  const [plan, setPlan] = useState<R | null>(null);
  const [lot, setLot] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const d: R | undefined = r.data || undefined;
  const cards: string[] = d?.cards || [];
  const cur = card || cards[0] || "";
  const mx: R[] = useMemo(() => (d?.matrix || []).filter((m: R) => m.card === cur), [d, cur]);
  const sizes = useMemo(() => Array.from(new Set(mx.map((m) => String(m.size)))), [mx]);
  if (r.loading && !d) return <Card title="Packing position"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Packing position"><Note tone="bad">{r.error || "Packing could not be read."}</Note></Card>;
  const s: R = d.summary || {}, pls: R[] = d.packing_lists || [], fis: R[] = d.inspections || [], nd: R[] = d.needle || [];
  const assorted = f.pack_type !== "Solid Colour Solid Size";
  const args = () => ({ sales_order: so, card: cur, pack_type: f.pack_type, pcs_per_carton: Number(f.pcs_per_carton) || 0, tail_carton_rule: f.tail_carton_rule, carton_start: Number(f.carton_start) || 1,
    ratios: assorted ? sizes.map((z) => ({ size: z, pieces_per_pack: Number(ratio[z]) || 0 })).filter((x) => x.pieces_per_pack > 0) : [] });
  const work = async () => {
    setBusy("plan");
    const res = await call("order_pack_plan", args());
    setBusy("");
    if (!res.ok) { setPlan(null); toast(res.error || "The plan could not be worked out.", "bad"); return; }
    setPlan(res.summary);
  };
  const fill = async (kind: string, extra: R = {}) => {
    setBusy(kind);
    const res = await call("order_prefill_pack", { ...(kind === "packing" ? args() : { sales_order: so }), kind, ...extra });
    setBusy("");
    if (!res.ok) { toast(res.error || "Could not pre-fill the form.", "bad"); return; }
    if (res.note) toast(res.note);
    cx?.newDoc?.(res.doctype, res.initial);
    onChanged();
  };
  const toggle = (n: string) => setLot((l) => (l.includes(n) ? l.filter((x) => x !== n) : [...l, n]));

  return (
    <>
      <Card title="Packing position" sub="Per colour and size: the order, what finished as A-grade, what is packed and what can still be packed (the production ledger).">
        {mx.length === 0 ? <Empty title="No production card" text="Issue and sew a production card first; packing starts from finished A-grade pieces." /> : (
          <>
            <div className="ws-grid ws-grid--kpi">
              <Kpi label="Order" value={num(s.order_qty)} /><Kpi label="Packable now" value={num(s.packable)} /><Kpi label="Packed (submitted)" value={num(s.packed)} />
              <Kpi label="Packed of order" value={`${num(s.pct_packed, 1)} %`} tone={s.pct_packed >= 100 ? "ok" : undefined} />
            </div>
            <div className="ws-table-wrap ws-mt"><table className="ws-table" aria-label="Packing position">
              <thead><tr><th>Colour</th><th>Size</th><th className="num">Order</th><th className="num">Finished A</th><th className="num">Packed</th><th className="num">Packable</th></tr></thead>
              <tbody>{mx.map((m, i) => <tr key={i}><td>{m.colour}</td><td>{m.size}</td><td className="num">{num(m.order_qty)}</td><td className="num">{num(m.fin_a)}</td><td className="num">{num(m.packed)}</td><td className="num"><b>{num(m.packable)}</b></td></tr>)}</tbody></table></div>
          </>)}
      </Card>

      <Card title="Carton plan" sub="Choose how it is packed; the ERP works out the cartons. Nothing is written until you make the packing list.">
        {!d.can_pack ? <Note>Your role can read the plan but not make packing lists.</Note> : mx.length === 0 ? <Empty title="Nothing to plan yet" /> : (
          <>
            <div className="ws-form">
              {cards.length > 1 && <Field label="Production card"><Select value={cur} onChange={setCard} options={cards} /></Field>}
              <Field label="Pack type"><Select value={f.pack_type} onChange={(v) => { setF({ ...f, pack_type: v }); setPlan(null); }} options={PACK_TYPES} /></Field>
              <Field label="Pieces per carton"><Input type="number" value={f.pcs_per_carton} onChange={(v) => { setF({ ...f, pcs_per_carton: v }); setPlan(null); }} /></Field>
              <Field label="Last carton"><Select value={f.tail_carton_rule} onChange={(v) => setF({ ...f, tail_carton_rule: v })} options={TAIL} /></Field>
              <Field label="First carton no"><Input type="number" value={f.carton_start} onChange={(v) => setF({ ...f, carton_start: v })} /></Field>
            </div>
            {assorted && (
              <div className="ws-mt"><div className="ws-small ws-muted">Ratio: pieces of each size in one pack</div>
                <div className="ws-form">{sizes.map((z) => <Field key={z} label={z}><Input type="number" value={ratio[z] ?? ""} onChange={(v) => { setRatio({ ...ratio, [z]: v }); setPlan(null); }} /></Field>)}</div></div>)}
            <div className="ws-row ws-mt" style={{ justifyContent: "flex-end" }}>
              <Btn busy={busy === "plan"} onClick={work}>Work out the plan</Btn>
              <Btn kind="primary" busy={busy === "packing"} onClick={() => fill("packing")}>Make the packing list</Btn>
            </div>
            {plan && (
              <div className="ws-mt">
                <div className="ws-table-wrap"><table className="ws-table" aria-label="Carton plan">
                  <thead><tr><th>Colour</th><th>Size</th><th className="num">Cartons</th><th className="num">Pieces</th><th className="num">Order</th><th className="num">Packable</th></tr></thead>
                  <tbody>{(plan.rows || []).map((x: R, i: number) => <tr key={i}><td>{x.colour}</td><td>{x.size}</td><td className="num">{num(x.cartons)}</td><td className="num"><b className={x.over ? "ws-matcell-late" : undefined}>{num(x.pieces)}</b></td><td className="num">{num(x.order_qty)}</td><td className="num">{num(x.packable)}</td></tr>)}
                    <tr><td colSpan={2}><b>Total</b></td><td className="num"><b>{num(plan.cartons)}</b></td><td className="num"><b>{num(plan.pieces)}</b></td><td className="num"><b>{num(plan.order_qty)}</b></td><td className="num">{num(plan.pct_of_order, 1)} % of order</td></tr></tbody></table></div>
                {plan.any_over && <div className="ws-mt"><Note tone="warn">A size is planned above what is packable. The ERP will refuse the list; reduce the pack.</Note></div>}
              </div>)}
          </>)}
      </Card>

      <Card title="Packing lists" sub="Tick submitted lists to make one final inspection over them (a lot covers one production card)."
        right={d.can_inspect ? <Btn sm kind="primary" disabled={!lot.length} busy={busy === "inspection"} onClick={() => fill("inspection", { packing_lists: lot })}>New final inspection{lot.length ? ` (${lot.length})` : ""}</Btn> : undefined} flush>
        {pls.length === 0 ? <Empty title="No packing list yet" /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Packing lists"><thead><tr><th /><th>Packing list</th><th>Pack</th><th className="num">Cartons</th><th className="num">Pieces</th><th className="num">% of order</th><th>Inspection</th><th>Status</th></tr></thead>
            <tbody>{pls.map((p) => (
              <tr key={p.name}><td>{p.can_inspect && d.can_inspect && <input type="checkbox" aria-label={`Pick ${p.name}`} checked={lot.includes(p.name)} onChange={() => toggle(p.name)} />}</td>
                <td><b className="ws-small">{p.name}</b><div className="ws-small ws-muted">{p.docstatus === 1 ? "submitted" : "draft"}{p.shipment ? ` · on ${p.shipment}` : ""}</div></td>
                <td className="ws-small">{p.pack_type}{p.pcs_per_carton ? ` · ${p.pcs_per_carton}/ctn` : ""}</td><td className="num">{num(p.total_cartons)}</td><td className="num">{num(p.total_pieces)}</td><td className="num">{num(p.total_vs_order_pct, 1)}</td>
                <td className="ws-small">{(p.inspections || []).join(", ") || "—"}</td>
                <td><Btn sm kind="plain" onClick={() => cx?.openDoc?.("Packing List", p.name)}><ExternalLink size={12} /> Open</Btn></td></tr>))}</tbody></table></div>)}
      </Card>

      <Card title="Final inspections" sub="What was found in the sample against what the AQL plan accepts, and the result." flush>
        {fis.length === 0 ? <Empty title="No final inspection yet" text="Submit a packing list, then inspect it." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Final inspections"><thead><tr><th>Inspection</th><th className="num">Sample</th><th className="num">Cartons</th><th>Critical</th><th>Major</th><th>Minor</th><th>Result</th><th /></tr></thead>
            <tbody>{fis.map((x) => {
              const cl = x.aql?.classes || {};
              const cell = (k: string) => <span className={cl[k]?.ok ? undefined : "ws-matcell-late"}>{num(cl[k]?.found)} / {num(cl[k]?.accept)}</span>;
              return (
                <tr key={x.name}><td><b className="ws-small">{x.name}</b><div className="ws-small ws-muted">{x.inspection_type} · {x.docstatus === 1 ? "submitted" : "draft"} · lot {(x.lots || []).join(", ")}</div></td>
                  <td className="num">{num(x.sample_size)}</td><td className="num">{num(x.inspected_cartons)}</td><td>{cell("critical")}</td><td>{cell("major")}</td><td>{cell("minor")}</td>
                  <td><Badge tone={RES_TONE[x.result]}>{x.result || "Not decided"}</Badge>{x.computed_result && x.computed_result !== x.result && <div className="ws-small ws-muted">AQL says {x.computed_result}</div>}</td>
                  <td><Btn sm kind="plain" onClick={() => cx?.openDoc?.("Final Inspection", x.name)}><ExternalLink size={12} /> Open</Btn></td></tr>);
            })}</tbody></table></div>)}
        <div className="ws-small ws-muted" style={{ padding: "6px 14px 10px" }}>Found / accepted by the plan. Red: more found than the plan accepts.</div>
      </Card>

      <Card title="Needle detector" sub="The line's metal check. A failure needs the rescan of everything since the last good check."
        right={d.can_needle ? <Btn sm kind="primary" busy={busy === "needle"} onClick={() => fill("needle")}>New needle check</Btn> : undefined} flush>
        {nd.length === 0 ? <Empty title="No check logged for this order's lines" /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Needle detector log"><thead><tr><th>Check</th><th>Line</th><th className="num">Test piece mm</th><th>Result</th><th className="num">Rescanned</th></tr></thead>
            <tbody>{nd.map((n) => <tr key={n.name} className="is-click" onClick={() => cx?.openDoc?.("Needle Detector Log", n.name)}><td><b className="ws-small">{n.name}</b><div className="ws-small ws-muted">{String(n.check_date || "").slice(0, 10)} {n.check_time || ""}</div></td>
              <td className="ws-small">{n.line}</td><td className="num">{num(n.test_piece_mm, 1)}</td><td><Badge tone={n.result === "Pass" ? "ok" : "bad"}>{n.result}</Badge></td><td className="num">{n.rescan_done ? "done" : num(n.garments_rescanned)}</td></tr>)}</tbody></table></div>)}
        {s.needle_failed && <div style={{ padding: "0 14px 12px" }}><Note tone="bad">A failed needle check has no rescan recorded.</Note></div>}
      </Card>
    </>
  );
}
