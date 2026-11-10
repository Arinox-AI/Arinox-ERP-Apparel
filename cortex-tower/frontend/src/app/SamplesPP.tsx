import { useState } from "react";
import { Check, ExternalLink, X } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Loading, Modal, Note, Select, Textarea, day, num, useCall } from "./kit";
import type { R, Tone } from "./kit";
import { useCx } from "../cx/ui";
import { useAct } from "./StepAct";

/* Step 4 of the Order page: samples and the PP meeting (ORDER_TO_SHIP_PLAN section 4). The approval matrix (sample type x style/colour, a cell is
   the status of the approval; click it for its rounds), the bulk gate card per style/colour (green only when the ERP's own gate script reports no
   blockers) and the PP meeting of each style. Everything shown comes from `order_samples_get`; every change is previewed, then confirmed. */

const DECISIONS = ["Pending", "Approved", "Approved with Comments", "Rejected", "Resubmit"];
const CATS = ["Fit", "Colour", "Fabric", "Trim", "Construction", "Label / Packing", "Measurement", "Other"];
const TONE: Record<string, Tone> = { ok: "ok", bad: "bad", warn: "warn" };

export function SamplesPP({ so, onChanged }: { so: string; onChanged: () => void }) {
  const cx = useCx();
  const r = useCall("order_samples_get", { sales_order: so }, []);
  const act = useAct(() => { onChanged(); void r.reload(true); });
  const [cell, setCell] = useState<{ row: R; type: string; c: R } | null>(null);
  const [meet, setMeet] = useState<R | null>(null);
  const [mk, setMk] = useState<{ style: string; card: string } | null>(null);
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <Card title="Approval matrix"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Approval matrix"><Note tone="bad">{r.error || "The samples could not be read."}</Note></Card>;
  const rows: R[] = d.rows || [], types: R[] = d.types || [], meetings: R[] = d.meetings || [], s: R = d.summary || {};
  const styles = Array.from(new Set(rows.map((x) => x.style_item)));

  return (
    <>
      <Card title="Approval matrix" sub="Each cell is the status of the approval the rules ask for. Click a cell for its rounds."
        right={d.can_write ? <Btn sm kind="primary" busy={act.busy} onClick={() => act.ask("order_samples_create", { sales_order: so }, "Create the sample approvals from the rules")}>Create from the rules</Btn> : undefined}>
        {rows.length === 0 || types.length === 0 ? <Empty title="No sample rules yet" text="Set the sample rules in Apparel Settings (or a Sample Requirement for the buyer); the matrix then shows what this order needs." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Approval matrix" style={{ minWidth: 560 }}>
            <thead><tr><th>Style / colour</th>{types.map((t) => <th key={t.type} title={`${t.gate}${t.per_colour ? ", per colour" : ""}`}>{t.type}</th>)}</tr></thead>
            <tbody>{rows.map((x) => (
              <tr key={x.style_item + x.colour}>
                <td><b className="ws-small">{x.style_item}</b><div className="ws-small ws-muted">{x.colour || "all colours"} · {num(x.qty)} pcs</div></td>
                {types.map((t) => { const c = x.cells[t.type] || {}; return (
                  <td key={t.type}>{c.status ? <button className="ws-cellbtn" onClick={() => setCell({ row: x, type: t.type, c })} aria-label={`${t.type} ${c.status}`}><Badge tone={TONE[c.tone]}>{c.status}</Badge></button> : <span className="ws-muted">·</span>}</td>); })}
              </tr>))}</tbody></table></div>)}
        {s.missing > 0 && <div className="ws-mt"><Note tone="warn">{s.missing} required approval(s) are not raised yet.</Note></div>}
      </Card>

      <Card title="Bulk gate" sub="Bulk production is blocked until every item below is in. The ERP's own gate decides; the tower only shows it.">
        <div className="ws-gates">{rows.map((x) => (
          <div key={x.style_item + x.colour} className={`ws-gate ${!x.gate.applies ? "" : x.gate.open ? "is-open" : "is-shut"}`} data-testid="gate-card">
            <div className="ws-row"><b className="ws-small">{x.style_item} / {x.colour || "all"}</b><span style={{ marginLeft: "auto" }} />
              {!x.gate.applies ? <Badge>Not applicable</Badge> : x.gate.open ? <Badge tone="ok"><Check size={11} /> Gate open</Badge> : <Badge tone="bad"><X size={11} /> Gate shut</Badge>}</div>
            {x.gate.blockers.length > 0 && <ul className="ws-small">{x.gate.blockers.map((b: string, i: number) => <li key={i}>{b}</li>)}</ul>}
          </div>))}</div>
      </Card>

      <Card title="PP meeting" sub="One per style, held after the production card is issued. Submitting it is the last condition of the gate.">
        <div className="ws-stack">{styles.map((st) => {
          const m = meetings.find((x) => x.style_item === st);
          return (
            <div key={st} className="ws-row" style={{ flexWrap: "wrap", gap: 10 }}>
              <b className="ws-small">{st}</b>
              {!m ? <><Badge>No meeting yet</Badge>{d.can_write && <Btn sm onClick={() => setMk({ style: st, card: "" })}>Make the PP meeting</Btn>}</>
                : <><Badge tone={m.docstatus === 1 ? "ok" : "warn"}>{m.docstatus === 1 ? "Submitted" : "Draft"}</Badge>
                  <span className="ws-small ws-muted">{m.name} · {m.open_actions} open action(s)</span>
                  <Btn sm onClick={() => setMeet(m)}>{m.docstatus === 1 ? "View" : "Edit and submit"}</Btn>
                  <Btn sm kind="plain" onClick={() => cx?.openDoc?.("PP Meeting", m.name)}><ExternalLink size={12} /> Open</Btn></>}
            </div>); })}</div>
      </Card>

      {cell && <RoundDrawer so={so} cell={cell} canWrite={!!d.can_write} onClose={() => setCell(null)} act={act} />}
      {meet && <MeetingEditor m={meet} canWrite={!!d.can_write} onClose={() => setMeet(null)} act={act} />}
      {mk && (
        <Modal title={`Make the PP meeting for ${mk.style}`} sub="A draft: the standard departments, fabric and trim readiness and every open buyer comment are filled in from the ERP." onClose={() => setMk(null)}
          foot={<><Btn onClick={() => setMk(null)}>Cancel</Btn><Btn kind="primary" onClick={() => { const p = { sales_order: so, style_item: mk.style, card_issued_on: mk.card }; setMk(null); void act.ask("order_pp_meeting_make", p, "Make the PP meeting"); }}>Preview</Btn></>}>
          <Field label="Production card issued on" hint="The meeting is held after this date."><Input type="date" value={mk.card} onChange={(v) => setMk({ ...mk, card: v })} /></Field>
        </Modal>)}
      {act.modal}
    </>
  );
}

function RoundDrawer({ so, cell, canWrite, onClose, act }: { so: string; cell: { row: R; type: string; c: R }; canWrite: boolean; onClose: () => void; act: ReturnType<typeof useAct> }) {
  const cx = useCx();
  const { c, type, row } = cell;
  const [f, setF] = useState({ decision: "Approved", sent_on: "", decision_on: "", comment: "", category: "Other", bulk: false });
  const rounds: R[] = c.rounds || [];
  const needs = ["Approved with Comments", "Rejected", "Resubmit"].includes(f.decision);
  return (
    <Modal wide title={`${type}: ${row.style_item} / ${row.colour || "all colours"}`} sub={c.sample ? `${c.sample} · ${c.status}${c.due_date ? ` · due ${day(c.due_date)}` : ""}` : "Not raised"} onClose={onClose}
      foot={<Btn onClick={onClose}>Close</Btn>}>
      {!c.sample ? <Note tone={c.status === "Missing" ? "bad" : undefined}>{c.status === "Missing" ? "The rules require this approval and none is raised. Use Create from the rules." : "Raise it when the buyer asks for it."}</Note> : (
        <>
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Rounds"><thead><tr><th>Round</th><th>Sent</th><th>Decision</th><th>Decided</th><th>Remarks</th></tr></thead>
            <tbody>{rounds.length === 0 ? <tr><td colSpan={5} className="ws-muted ws-small">No round yet.</td></tr> : rounds.map((x) => (
              <tr key={x.round_no}><td>{x.round_no}</td><td>{day(x.sent_on)}</td><td><Badge tone={x.decision === "Approved" || x.decision === "Approved with Comments" ? "ok" : x.decision === "Rejected" ? "bad" : "warn"}>{x.decision}</Badge></td><td>{x.decision_on ? day(x.decision_on) : "—"}</td><td className="ws-small">{x.remarks || ""}</td></tr>))}</tbody></table></div>
          {canWrite && (
            <div className="ws-mt ws-stack">
              <b className="ws-small">Record a round</b>
              <div className="ws-form">
                <Field label="Decision"><Select value={f.decision} onChange={(v) => setF({ ...f, decision: v })} options={DECISIONS} /></Field>
                <Field label={f.decision === "Pending" ? "Sent on" : "Decided on"}><Input type="date" value={f.decision === "Pending" ? f.sent_on : f.decision_on} onChange={(v) => setF(f.decision === "Pending" ? { ...f, sent_on: v } : { ...f, decision_on: v })} /></Field>
                {needs && <Field label="Category"><Select value={f.category} onChange={(v) => setF({ ...f, category: v })} options={CATS} /></Field>}
                {needs && <Field label="Buyer's comment" wide><Textarea rows={3} value={f.comment} onChange={(v) => setF({ ...f, comment: v })} /></Field>}
                {type === "PP" && <label className="ws-small"><input type="checkbox" checked={f.bulk} onChange={(e) => setF({ ...f, bulk: e.target.checked })} /> Made in bulk fabric (the ERP will not approve a PP sample otherwise)</label>}
              </div>
              <div className="ws-row"><Btn kind="primary" busy={act.busy} onClick={() => { onClose(); void act.ask("order_sample_round", { sales_order: so, sample_approval: c.sample, decision: f.decision, sent_on: f.sent_on, decision_on: f.decision_on, comment: f.comment, category: f.category, in_bulk_fabric: f.bulk }, `Record the round on ${c.sample}`); }}>Preview and save</Btn>
                {["Fit", "Size Set", "PP", "Proto"].includes(type) && <Btn onClick={() => { onClose(); void act.ask("order_sample_load", { sales_order: so, sample_approval: c.sample, what: "spec", sample_size: "" }, "Load the Tech Pack spec"); }}>Load the Tech Pack spec</Btn>}
                {type.includes("Test") && <Btn onClick={() => { onClose(); void act.ask("order_sample_load", { sales_order: so, sample_approval: c.sample, what: "tests" }, "Load the standard tests"); }}>Load the standard tests</Btn>}
                <Btn kind="plain" onClick={() => cx?.openDoc?.("Sample Approval", c.sample)}><ExternalLink size={12} /> Open the form</Btn></div>
            </div>)}
        </>)}
    </Modal>
  );
}

function MeetingEditor({ m, canWrite, onClose, act }: { m: R; canWrite: boolean; onClose: () => void; act: ReturnType<typeof useAct> }) {
  const draft = m.docstatus === 0 && canWrite;
  const [att, setAtt] = useState<string[]>((m.participants || []).filter((p: R) => p.attended).map((p: R) => p.department));
  const [acts, setActs] = useState<R[]>((m.actions || []).map((a: R, i: number) => ({ ...a, idx: a.idx || i + 1 })));
  const [card, setCard] = useState(m.production_card_issued_on || "");
  const patch = (i: number, p: R) => setActs((x) => x.map((a, k) => (k === i ? { ...a, ...p } : a)));
  return (
    <Modal wide title={`PP meeting ${m.name}`} sub={`${m.style_item} · ${m.docstatus === 1 ? "submitted" : "draft"}`} onClose={onClose}
      foot={<><Btn onClick={onClose}>Close</Btn>{draft && <>
        <Btn busy={act.busy} onClick={() => { onClose(); void act.ask("order_pp_meeting_actions", { name: m.name, attended: att, card_issued_on: card, actions: acts.map((a) => ({ idx: a.idx, action_taken: a.action_taken, action_owner: a.action_owner, target_date: a.target_date })) }, "Save the meeting"); }}>Preview and save</Btn>
        <Btn kind="primary" busy={act.busy} onClick={() => { onClose(); void act.ask("order_pp_meeting_submit", { name: m.name }, "Submit the PP meeting"); }}>Submit the meeting</Btn></>}</>}>
      {draft && <Field label="Production card issued on"><Input type="date" value={card} onChange={setCard} /></Field>}
      <b className="ws-small">Attendance</b>
      <div className="ws-chips ws-mb">{(m.participants || []).map((p: R) => (
        <label key={p.department} className="ws-small" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" disabled={!draft} checked={att.includes(p.department)} onChange={(e) => setAtt(e.target.checked ? [...att, p.department] : att.filter((x) => x !== p.department))} />{p.department}</label>))}</div>
      <b className="ws-small">Actions</b>
      {acts.length === 0 ? <div className="ws-small ws-muted">No buyer comment is open for this style.</div> : (
        <div className="ws-table-wrap"><table className="ws-table ws-table--edit" aria-label="Meeting actions" style={{ minWidth: 640 }}><thead><tr><th>Comment</th><th>Action taken</th><th>Owner (user)</th><th>Target date</th></tr></thead>
          <tbody>{acts.map((a, i) => (<tr key={a.idx}><td className="ws-small">{a.comment}</td>
            <td><Input sm disabled={!draft} value={a.action_taken} onChange={(v) => patch(i, { action_taken: v })} aria-label="Action taken" /></td>
            <td><Input sm disabled={!draft} value={a.action_owner} onChange={(v) => patch(i, { action_owner: v })} aria-label="Owner" /></td>
            <td><Input sm type="date" disabled={!draft} value={a.target_date} onChange={(v) => patch(i, { target_date: v })} aria-label="Target date" /></td></tr>))}</tbody></table></div>)}
    </Modal>
  );
}
