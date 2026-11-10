import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Kpi, Loading, Modal, Note, Select, Textarea, call, num, useCall, useToast } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";
import { useAct } from "./StepAct";

/* Step 6 of the Order page: cut and sew (ORDER_TO_SHIP_PLAN section 4). The production matrix is the ERP's own `arinox_production_card_get_summary`
   (stage totals of the Production Movement ledger per colour x size) with the percentage of the order and what was posted today. Actions: save, issue and
   revise the production card; suggest, release, approve and reopen a cut plan; issue fabric to the cutting floor (a manager approves that); activate the
   operation bulletin; and the floor documents (daily line report, lay report, line input) opened in the generic form, pre-filled. */

const TONE: Record<string, Tone> = { Released: "ok", Draft: "warn", "Pending Approval": "bad", Active: "ok", Superseded: undefined };
const HEAD = ["factory", "line", "ex_factory_date", "pcd", "bundle_size", "default_extra_cut_pct"];

export function CutSew({ so, onChanged }: { so: string; onChanged: () => void }) {
  const cx = useCx();
  const toast = useToast();
  const r = useCall("order_cutsew_get", { sales_order: so }, []);
  const act = useAct(() => { onChanged(); void r.reload(true); });
  const [ed, setEd] = useState<{ style: R; header: R; lines: R[]; fabrics: R[]; processes: R[]; name?: string } | null>(null);
  const [reason, setReason] = useState<{ fn: string; params: R; title: string; field: string; text: string } | null>(null);
  const [sug, setSug] = useState<{ name: string; data: any } | null>(null);
  const [issue, setIssue] = useState<{ card: string; rolls: R[] } | null>(null);
  const [busy, setBusy] = useState("");
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <Card title="Production matrix"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Production matrix"><Note tone="bad">{r.error || "Production could not be read."}</Note></Card>;
  const mx: R = d.matrix || {}, stages: R[] = mx.stages || [], tot: R = mx.totals || {}, pct: R = mx.pct || {}, today: R = mx.today || {};
  const cards: R[] = d.cards || [], plans: R[] = d.cut_plans || [], obs: R[] = d.bulletins || [], reps: R[] = d.reports || [], s: R = d.summary || {};
  const live = cards.filter((c) => c.docstatus === 1 && c.status !== "Superseded" && c.status !== "Cancelled");
  const w = !!d.can_write;

  const fill = async (kind: string, extra: R = {}) => {
    setBusy(kind);
    const res = await call("order_prefill", { sales_order: so, kind, ...extra });
    setBusy("");
    if (!res.ok) { toast(res.error || "Could not pre-fill the form.", "bad"); return; }
    if (res.note) toast(res.note);
    cx?.newDoc?.(res.doctype, res.initial);
  };
  const newCard = async (style?: string) => {
    setBusy("card");
    const res = await call("order_card_context", { sales_order: so, style_item: style || "" });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP could not give the order's lines.", "bad"); return; }
    const st = (res.styles || []).find((x: R) => !x.card) || (res.styles || [])[0];
    if (!st) { toast("The order has no style lines.", "bad"); return; }
    const a = (st.allocation || [])[0] || {};
    setEd({ style: st, header: { factory: a.factory || "", line: a.line || "", ex_factory_date: st.ex_factory_date || "", pcd: a.pcd || "", bundle_size: res.defaults?.bundle_size || "", default_extra_cut_pct: res.defaults?.extra_cut_pct ?? "" },
      lines: (st.lines || []).map((l: R) => ({ ...l, extra_cut_pct: res.defaults?.extra_cut_pct ?? "" })), fabrics: st.fabrics || [], processes: [] });
  };
  const suggest = async (name: string) => {
    setBusy("s" + name);
    const res = await call("order_cutplan_suggest", { name });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP could not suggest rolls.", "bad"); return; }
    setSug({ name, data: res.suggestion });
  };
  const openIssue = async (card: string) => {
    setBusy("i" + card);
    const res = await call("order_cut_issuable", { card });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP could not list the rolls.", "bad"); return; }
    setIssue({ card, rolls: (res.rolls || []).map((x: R) => ({ ...x, qty: "" })) });
  };

  return (
    <>
      <Card title="Production matrix" sub="Stage totals from the production ledger, against the order quantity. Finished = received in finishing; QC pass = A-grade passes of the finishing audit."
        right={<Btn sm onClick={() => r.reload(true)}>Refresh</Btn>}>
        {live.length === 0 ? <Empty title="No production card yet" text="Make and issue the production card: the matrix then fills as the floor documents are submitted." /> : (
          <>
            <div className="ws-grid ws-grid--kpi">
              {stages.map((st) => <Kpi key={st.key} label={st.label} value={num(tot[st.key])} hint={`${num(pct[st.key], 1)}% of ${num(tot.order_qty)} · today ${num(today[st.key])}`} tone={st.key === "sewn" && pct.sewn >= 100 ? "ok" : undefined} />)}
            </div>
            {(mx.cards || []).map((c: R) => (
              <div key={c.card} className="ws-mt">
                <div className="ws-small ws-muted">{c.style} · {c.card} · {c.status}</div>
                <div className="ws-table-wrap"><table className="ws-table" aria-label={`Production matrix ${c.card}`} style={{ minWidth: 640 }}>
                  <thead><tr><th>Colour</th><th>Size</th><th className="num">Order</th>{stages.map((st) => <th key={st.key} className="num">{st.label}</th>)}<th className="num">Sewn %</th></tr></thead>
                  <tbody>{(c.rows || []).map((x: R, i: number) => (
                    <tr key={i}><td>{x.colour}</td><td>{x.size}</td><td className="num">{num(x.order_qty)}</td>{stages.map((st) => <td key={st.key} className="num">{num(x[st.key])}</td>)}
                      <td className="num">{x.order_qty ? num((x.sewn / x.order_qty) * 100, 0) + "%" : "—"}</td></tr>))}</tbody></table></div>
              </div>))}
            <div className="ws-mt">{s.order_qty > 0 && s.sewn >= s.order_qty ? <Note tone="ok">Sewn {num(s.sewn)} of {num(s.order_qty)}: the sewing is complete.</Note>
              : <Note tone="warn">Sewn {num(s.sewn)} of {num(s.order_qty)} ({num(s.sewn_pct, 1)}%); cut {num(s.cut)}.</Note>}</div>
          </>)}
        {(d.styles_without_card || []).length > 0 && live.length > 0 && <div className="ws-mt"><Note tone="warn">No production card yet for: {d.styles_without_card.join(", ")}.</Note></div>}
      </Card>

      <Card title="Production cards" sub="Save a draft from the order's lines, issue it, revise it when the order changes." right={w ? <Btn sm kind="primary" busy={busy === "card"} onClick={() => newCard()}>New production card</Btn> : undefined}>
        {cards.length === 0 ? <div className="ws-small ws-muted">None yet.</div> : (
          <div className="ws-stack">{cards.map((c) => (
            <div key={c.name} className="ws-row" style={{ flexWrap: "wrap", gap: 8 }}>
              <b className="ws-small">{c.name}</b><span className="ws-small ws-muted">{c.style_no || c.style_item} · rev {c.revision_no || 0}</span><Badge tone={c.docstatus === 1 ? "ok" : "warn"}>{c.status}</Badge>
              {w && c.can_approve && <Btn sm onClick={() => act.ask("order_card_approve", { name: c.name }, `Issue ${c.name}`)}>Issue</Btn>}
              {w && c.can_revise && <Btn sm onClick={() => setReason({ fn: "order_card_revise", params: { name: c.name }, title: `Revise ${c.name}`, field: "reason", text: "" })}>Revise</Btn>}
              {w && c.can_revise && <Btn sm busy={busy === "i" + c.name} onClick={() => openIssue(c.name)}>Issue fabric</Btn>}
              <Btn sm kind="plain" onClick={() => cx?.openDoc?.("Production Card", c.name)}><ExternalLink size={12} /> Open</Btn>
            </div>))}</div>)}
      </Card>

      <Card title="Cut plans" sub="Suggest rolls, release (a variance above the limit goes to a manager), approve with a reason, reopen before a lay is cut."
        right={w && live.length > 0 ? <Btn sm busy={busy === "cut_plan"} onClick={() => fill("cut_plan")}>New cut plan</Btn> : undefined}>
        {plans.length === 0 ? <div className="ws-small ws-muted">No cut plan yet.</div> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Cut plans"><thead><tr><th>Plan</th><th>Colour / fabric</th><th className="num">Variance</th><th>Status</th><th /></tr></thead>
            <tbody>{plans.map((p) => (
              <tr key={p.name}><td><b className="ws-small">{p.name}</b><div className="ws-small ws-muted">{p.production_card}</div></td><td className="ws-small">{p.colour} · {p.fabric_item}</td>
                <td className="num">{p.variance_pct !== undefined && p.variance_pct !== null ? num(p.variance_pct, 1) + "%" : "—"}</td><td><Badge tone={TONE[p.status]}>{p.status}</Badge></td>
                <td style={{ whiteSpace: "nowrap" }}>{w && <>
                  <Btn sm busy={busy === "s" + p.name} onClick={() => suggest(p.name)}>Suggest rolls</Btn>
                  {p.can_release && <Btn sm onClick={() => act.ask("order_cutplan_release", { name: p.name }, `Release ${p.name}`)}>Release</Btn>}
                  {p.can_approve && <Btn sm kind="primary" onClick={() => setReason({ fn: "order_cutplan_approve", params: { name: p.name }, title: `Approve the marker of ${p.name}`, field: "note", text: "" })}>Approve</Btn>}
                  {p.can_reopen && <Btn sm onClick={() => act.ask("order_cutplan_reopen", { name: p.name }, `Reopen ${p.name}`)}>Reopen</Btn>}
                  {p.status === "Released" && <Btn sm onClick={() => fill("lay", { name: p.name, card: p.production_card })}>Lay report</Btn>}</>}</td></tr>))}</tbody></table></div>)}
      </Card>

      <Card title="Operation bulletin" sub="The active bulletin of a style sets the target and the efficiency of the daily line report.">
        {obs.length === 0 ? <div className="ws-small ws-muted">No operation bulletin for the styles of this order.</div> : (
          <div className="ws-stack">{obs.map((o) => (
            <div key={o.name} className="ws-row" style={{ flexWrap: "wrap", gap: 8 }}>
              <b className="ws-small">{o.name}</b><span className="ws-small ws-muted">{o.style_item} · v{o.version} · SAM {num(o.total_sam, 1)} · {num(o.operators)} operators</span><Badge tone={TONE[o.status]}>{o.status}</Badge>
              {w && o.status === "Draft" && <Btn sm onClick={() => act.ask("order_ob_activate", { name: o.name }, `Activate ${o.name}`)}>Activate</Btn>}
              <Btn sm kind="plain" onClick={() => cx?.openDoc?.("Operation Bulletin", o.name)}><ExternalLink size={12} /> Open</Btn></div>))}</div>)}
        {w && <div className="ws-mt"><Btn sm busy={busy === "operation_bulletin"} onClick={() => fill("operation_bulletin")}>New operation bulletin</Btn></div>}
      </Card>

      <Card title="Floor documents" sub="Opened in the form, pre-filled. Submitting one posts the production ledger (a manager approves that)."
        right={w && live.length > 0 ? <><Btn sm kind="primary" busy={busy === "dlr"} onClick={() => fill("dlr")}>Daily line report</Btn><Btn sm busy={busy === "lay"} onClick={() => fill("lay")}>Lay report</Btn><Btn sm busy={busy === "line_input"} onClick={() => fill("line_input")}>Line input</Btn></> : undefined} flush>
        {reps.length === 0 ? <Empty title="No line or lay report yet" text="Report what the line sewed each day; the matrix above follows the ledger." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Line and lay reports"><thead><tr><th>Document</th><th>Date</th><th>Line</th><th className="num">Pieces</th><th>Status</th></tr></thead>
            <tbody>{reps.map((x) => (
              <tr key={x.name} className="is-click" onClick={() => cx?.openDoc?.(x.doctype, x.name)}><td><div className="ws-small ws-muted">{x.doctype}</div><b className="ws-small">{x.name}</b></td><td className="ws-small">{x.date}</td>
                <td className="ws-small">{x.line || "—"}</td><td className="num">{num(x.qty)}</td><td><Badge tone={x.docstatus === 1 ? "ok" : "warn"}>{x.docstatus === 1 ? "Submitted" : "Draft"}</Badge></td></tr>))}</tbody></table></div>)}
      </Card>

      {ed && (
        <Modal wide title="Production card: draft" sub="Lines come from the Sales Order; set where and when, then preview and save. Lines without an order quantity are never sent." onClose={() => setEd(null)}
          foot={<><Btn onClick={() => setEd(null)}>Close</Btn><Btn kind="primary" busy={act.busy} onClick={() => { const p = { sales_order: so, style_item: ed.style.style_item, header: ed.header, lines: ed.lines, fabrics: ed.fabrics, processes: ed.processes }; setEd(null); void act.ask("order_card_save", p, "Save the draft production card"); }}>Preview and save</Btn></>}>
          <div className="ws-form" style={{ gridTemplateColumns: "1fr 1fr" }}>{HEAD.map((k) => <Field key={k} label={k.replace(/_/g, " ")}><Input value={ed.header[k]} type={k.includes("date") || k === "pcd" ? "date" : undefined} num={k === "bundle_size" || k.includes("pct")} onChange={(v) => setEd({ ...ed, header: { ...ed.header, [k]: v } })} /></Field>)}</div>
          <div className="ws-table-wrap ws-mt"><table className="ws-table ws-table--edit" aria-label="Card lines"><thead><tr><th>Colour</th><th>Size</th><th className="num">Order qty</th><th className="num">Extra cut %</th></tr></thead>
            <tbody>{ed.lines.map((l, i) => (
              <tr key={i}><td>{l.colour}</td><td>{l.size}</td><td className="num">{num(l.order_qty)}</td>
                <td><Input sm num value={l.extra_cut_pct} aria-label="extra cut" onChange={(v) => setEd({ ...ed, lines: ed.lines.map((x, k) => (k === i ? { ...x, extra_cut_pct: v } : x)) })} /></td></tr>))}</tbody></table></div>
          {ed.fabrics.length > 0 ? <div className="ws-table-wrap ws-mt"><table className="ws-table" aria-label="Card fabrics"><thead><tr><th>Colour</th><th>Fabric</th><th className="num">Consumption</th></tr></thead>
            <tbody>{ed.fabrics.map((f, i) => <tr key={i}><td>{f.colour}</td><td className="ws-small">{f.fabric_item}</td><td className="num">{num(f.consumption, 3)}</td></tr>)}</tbody></table></div>
            : <div className="ws-mt"><Note tone="warn">No approved fabric requisition for this style: the card has no fabric, so fabric cannot be issued to cutting.</Note></div>}
          <div className="ws-mt"><b className="ws-small">Subcontract route</b> <span className="ws-small ws-muted">(wash, print, embroidery: a challan can only go to a process on the route)</span>
            {ed.processes.map((p, i) => (
              <div key={i} className="ws-row" style={{ gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                <Input sm value={p.subcontract_process} placeholder="Process" aria-label="process" onChange={(v) => setEd({ ...ed, processes: ed.processes.map((x, k) => (k === i ? { ...x, subcontract_process: v } : x)) })} />
                <Select sm value={p.position} options={["Before Sewing", "After Sewing"]} onChange={(v) => setEd({ ...ed, processes: ed.processes.map((x, k) => (k === i ? { ...x, position: v } : x)) })} />
                <Input sm value={p.supplier} placeholder="Supplier" aria-label="supplier" onChange={(v) => setEd({ ...ed, processes: ed.processes.map((x, k) => (k === i ? { ...x, supplier: v } : x)) })} />
                <Btn sm kind="plain" onClick={() => setEd({ ...ed, processes: ed.processes.filter((_x, k) => k !== i) })}>Remove</Btn></div>))}
            <div className="ws-mt"><Btn sm onClick={() => setEd({ ...ed, processes: [...ed.processes, { subcontract_process: "", position: "After Sewing", sequence: ed.processes.length + 1, supplier: "" }] })}>Add a process</Btn></div></div>
        </Modal>)}
      {reason && (
        <Modal title={reason.title} sub="A reason is required." onClose={() => setReason(null)}
          foot={<><Btn onClick={() => setReason(null)}>Cancel</Btn><Btn kind="primary" disabled={!reason.text.trim()} onClick={() => { const p = { ...reason.params, [reason.field]: reason.text }; const fn = reason.fn, t = reason.title; setReason(null); void act.ask(fn, p, t); }}>Preview</Btn></>}>
          <Field label="Reason" wide><Textarea rows={4} value={reason.text} onChange={(v) => setReason({ ...reason, text: v })} /></Field>
        </Modal>)}
      {sug && (
        <Modal title={`Suggested rolls for ${sug.name}`} sub="From the ERP. Nothing is saved: add the rolls to the lays in the cut plan." onClose={() => setSug(null)} foot={<Btn onClick={() => setSug(null)}>Close</Btn>}>
          <pre className="ws-small" style={{ whiteSpace: "pre-wrap", maxHeight: 360, overflow: "auto" }}>{JSON.stringify(sug.data, null, 1)}</pre>
        </Modal>)}
      {issue && (
        <Modal wide title={`Issue fabric to cutting for ${issue.card}`} sub="Accepted rolls in the fabric store. Enter the length to issue per roll; rolls without a length are not sent. A manager approves the Stock Entry." onClose={() => setIssue(null)}
          foot={<><Btn onClick={() => setIssue(null)}>Cancel</Btn><Btn kind="primary" onClick={() => { const p = { card: issue.card, rolls: issue.rolls.filter((x) => Number(x.qty) > 0).map((x) => ({ batch_no: x.batch, qty: Number(x.qty) })) }; setIssue(null); void act.ask("order_cut_issue", p, "Issue the fabric"); }}>Preview</Btn></>}>
          {issue.rolls.length === 0 ? <Note>No accepted roll is free for the fabrics of this card.</Note> : (
            <div className="ws-table-wrap"><table className="ws-table ws-table--edit" aria-label="Rolls"><thead><tr><th>Roll</th><th>Colour</th><th>Shade</th><th className="num">Free (m)</th><th className="num">Issue (m)</th></tr></thead>
              <tbody>{issue.rolls.map((x, i) => (
                <tr key={x.batch}><td className="ws-small">{x.roll_no || x.batch}<div className="ws-muted">{x.item}</div></td><td className="ws-small">{x.colour}</td><td className="ws-small">{x.shade || "—"}</td><td className="num">{num(x.available_m, 1)}</td>
                  <td><Input sm num value={x.qty} aria-label="issue" onChange={(v) => setIssue({ ...issue, rolls: issue.rolls.map((y, k) => (k === i ? { ...y, qty: v } : y)) })} /></td></tr>))}</tbody></table></div>)}
        </Modal>)}
      {act.modal}
    </>
  );
}
