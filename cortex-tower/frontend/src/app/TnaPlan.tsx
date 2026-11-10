import { useState } from "react";
import { ExternalLink, Lock } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Loading, Modal, Note, Select, Textarea, call, day, useCall, useToast } from "./kit";
import type { R, Tone } from "./kit";

/* Step 3 of the Order page: the T&A plan (TNA plan phases 0 and 1). Three date lanes per milestone: baseline (planned), forecast, actual.
   The tower computes the plan (`order_tna_get`), the ERP's Order TNA is the plan of record (`order_tna_make` writes it in one call),
   the baseline is locked once agreed, and a locked plan moves only by a revision with a party and a reason. Calendars are seven-day (D5). */

const TONE: Record<string, Tone> = { Done: "ok", "On track": "info", "At risk": "warn", Overdue: "bad", "Not recorded": "violet", "Not Applicable": undefined };
const PARTIES = ["Buyer", "Supplier", "Factory", "Logistics", "Other"];

export function TnaPlan({ so, onChanged }: { so: string; onChanged: () => void }) {
  const toast = useToast();
  const r = useCall("order_tna_get", { sales_order: so }, []);
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState<R | null>(null);
  const [rev, setRev] = useState<{ plan: R; code: string; date: string; party: string; note: string } | null>(null);
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <Card title="T&A plan"><Loading rows={3} /></Card>;
  if (!d) return <Card title="T&A plan"><Note tone="bad">{r.error || "The T&A could not be read."}</Note></Card>;

  const make = async (preview: boolean) => {
    setBusy(preview ? "preview" : "make");
    const res = await call("order_tna_make", { sales_order: so, preview });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP refused it.", "bad"); return; }
    if (preview) { setConfirm(res); return; }
    setConfirm(null); toast(`T&A written: ${(res.written || []).length} plan(s).`); onChanged(); void r.reload(true);
  };
  const lock = async (plan: R) => {
    setBusy("lock:" + plan.order_tna);
    const res = await call("order_tna_lock", { sales_order: so, order_tna: plan.order_tna });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP refused the lock.", "bad"); return; }
    toast(`Baseline version ${res.version} locked.`); onChanged(); void r.reload(true);
  };
  const doRevise = async () => {
    if (!rev) return;
    setBusy("rev");
    const res = await call("order_tna_revise", { sales_order: so, order_tna: rev.plan.order_tna, code: rev.code, new_date: rev.date, reason_code: rev.party, note: rev.note });
    setBusy("");
    if (!res.ok) { toast(res.error || "Refused.", "bad"); return; }
    setRev(null); toast(`Revised. Ship forecast ${day(res.ship_before)} to ${day(res.ship_after)}.`); onChanged(); void r.reload(true);
  };

  const plans: R[] = d.plans || [];
  return (
    <>
      {d.proposed && (
        <Card title="Make the plan" sub={d.note}
          right={<><Btn sm busy={busy === "preview"} onClick={() => make(true)}>Preview</Btn></>}>
          <div className="ws-small ws-muted">The dates below are the tower's proposal: the template's lead times counted back from ex-factory on a seven-day calendar, pinned to the allocation's PCD when there is one.</div>
        </Card>)}
      {plans.map((p) => {
        const s: R = p.summary || {};
        const rows: R[] = (p.rows || []).filter((x: R) => all || x.status !== "Done" && (x.is_critical || x.status !== "On track" || x.critical));
        return (
          <Card key={p.order_tna || "x"} title={`${p.style_no || "Order"}${p.colour ? " / " + p.colour : ""}`} sub={`ex-factory ${day(p.ex_factory)}${p.qty ? " · " + p.qty + " pcs" : ""}`}
            right={<>
              {p.locked ? <Badge tone="dark"><Lock size={11} /> Baseline locked{(p.baselines || []).length ? ` v${p.baselines[p.baselines.length - 1].version}` : ""}</Badge> : !d.proposed && <Btn sm busy={busy === "lock:" + p.order_tna} onClick={() => lock(p)}><Lock size={13} /> Lock baseline</Btn>}
              {p.url && <Btn sm onClick={() => window.open(p.url, "_blank", "noopener")}><ExternalLink size={13} /> ERP</Btn>}</>}>
            <Note tone={s.feasible && s.plan_feasible ? "ok" : "bad"}>{s.message}{s.driver && !s.feasible ? ` Chase: ${s.driver}.` : ""}</Note>
            <div className="ws-row ws-mt ws-small ws-muted">
              <span>Ship forecast <b>{day(s.ship_forecast)}</b></span><span>{s.critical} critical milestones</span><span>{(s.late || []).length} late or at risk</span>
              <span style={{ marginLeft: "auto" }}><label><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show all {(p.rows || []).length}</label></span>
            </div>
            <div className="ws-table-wrap ws-mt"><table className="ws-table" aria-label="T&A milestones" style={{ minWidth: 820 }}>
              <thead><tr><th>Milestone</th><th>Owner</th><th>Baseline</th><th>Forecast</th><th>Actual</th><th className="num">Float</th><th>Status</th><th /></tr></thead>
              <tbody>{rows.length === 0 ? <tr><td colSpan={8}><Empty title="Nothing late or critical" text="Tick “Show all” to see every milestone." /></td></tr> : rows.map((x) => (
                <tr key={x.code}>
                  <td><b className="ws-small">{x.name}</b><div className="ws-small ws-muted">{x.code}{x.pinned ? " · pinned" : ""}</div></td>
                  <td className="ws-small">{x.owner_role}</td>
                  <td className="ws-small">{day(x.planned_finish)}</td>
                  <td className="ws-small" style={{ color: x.slip_wd > 0 ? "var(--ws-bad)" : undefined }}>{day(x.forecast_finish)}{x.slip_wd > 0 ? ` (+${x.slip_wd})` : ""}</td>
                  <td className="ws-small">{x.actual_date ? day(x.actual_date) : "—"}{x.source ? <div className="ws-muted">{x.source}</div> : null}</td>
                  <td className="num ws-small">{x.float_wd}</td>
                  <td><Badge tone={TONE[x.status]}>{x.status}</Badge></td>
                  <td>{p.locked && !x.actual_date && x.stored ? <Btn sm kind="plain" onClick={() => setRev({ plan: p, code: x.code, date: String(x.forecast_finish || "").slice(0, 10), party: "", note: "" })}>Revise</Btn> : null}</td>
                </tr>))}</tbody></table></div>
            {(p.revisions || []).length > 0 && (
              <div className="ws-mt"><div className="ws-small ws-muted" style={{ fontWeight: 600 }}>Revisions</div>
                {p.revisions.slice(0, 5).map((v: R, i: number) => <div key={i} className="ws-small">{v.code}: {day(v.old)} to {day(v.new)} · {v.reason_code} · {v.note} <span className="ws-muted">({v.by}{v.approved_by ? `, approved by ${v.approved_by}` : ""}, ship {v.ship_impact_wd >= 0 ? "+" : ""}{v.ship_impact_wd} days)</span></div>)}</div>)}
            {!d.proposed && !p.locked && <div className="ws-small ws-muted ws-mt">Locking freezes the baseline. After that a date moves only by a revision with a party and a reason, and a move of the ship date needs a manager.</div>}
          </Card>);
      })}
      {d.proposed && plans.length > 0 && <div className="ws-row"><Btn kind="primary" busy={busy === "make"} onClick={() => make(false)}>Make the T&A in the ERP</Btn><span className="ws-small ws-muted">Creates the Order TNA and its milestones. You can lock the baseline once it is written.</span></div>}

      {confirm && (
        <Modal title="Make the T&A in the ERP?" sub="This is what the ERP will do. Nothing has been written yet." onClose={() => setConfirm(null)}
          foot={<><Btn onClick={() => setConfirm(null)}>Cancel</Btn><Btn kind="primary" busy={busy === "make"} onClick={() => make(false)}>Confirm and make</Btn></>}>
          {(confirm.preview || []).flatMap((pv: R) => pv?.operations || []).map((o: R, i: number) => <div key={i} className="ws-small ws-muted">{o.op} {o.doctype} {o.name}</div>)}
          <div className="ws-small ws-mt">Then every milestone's planned date is written in one call per plan.</div>
        </Modal>)}
      {rev && (
        <Modal title={`Revise ${rev.code}`} sub="The baseline does not move. The revised date, who caused it and why are kept." onClose={() => setRev(null)}
          foot={<><Btn onClick={() => setRev(null)}>Cancel</Btn><Btn kind="primary" busy={busy === "rev"} onClick={doRevise}>Save the revision</Btn></>}>
          <div className="ws-grid ws-grid--2">
            <Field label="New date"><Input type="date" value={rev.date} onChange={(v) => setRev({ ...rev, date: v })} /></Field>
            <Field label="Who caused it"><Select value={rev.party} onChange={(v) => setRev({ ...rev, party: v })} placeholder="Choose" options={PARTIES} /></Field>
            <Field label="Why" wide><Textarea rows={3} value={rev.note} onChange={(v) => setRev({ ...rev, note: v })} /></Field>
          </div>
        </Modal>)}
    </>
  );
}
