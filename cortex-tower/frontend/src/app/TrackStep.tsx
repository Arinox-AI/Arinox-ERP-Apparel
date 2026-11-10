/* Moved to the Order page, step 9 (Ship), on 2026-11-09 (S9): the Deal page now links there. Same component, same backend (`deal_track*`).
   ───────────────────────── ship & track ─────────────────────────
   The contract is the promise. This tab is what the promise costs us afterwards: the factory clock (ex-factory → ETD →
   ETA → warehouse → payment), the papers the contract names (who produces each, and by which day), and the goods
   themselves (booking, cut-off, flight/vessel, HBL/MBL/AWB, tracking link and status).

   Nothing on this page is a guess. Every date comes from the contract's own terms, and a date that is not on file says
   so instead of being invented. The papers can be ticked off here because the ERP has no field for "the buyer has it
   now"; the tracking facts are written to the ERP's own Shipment, never to a copy of it. */
import { useEffect, useState } from "react";
import { Copy, ExternalLink, FileText, RefreshCw, Truck } from "lucide-react";
import { Btn, Card, Empty, Field, Input, Loading, Note, Select, call, day, useToast } from "./kit";
import type { R } from "./kit";

type Row = {
  id?: string; key: string; label: string; date: string; days_left: number | null; state: string; basis: string;
  kind: string; owner?: string; given_on?: string; given_by?: string; note?: string; ticked?: boolean;
};
type Track = {
  ok: boolean; contract: string; sales_order: string; signed: boolean; schedule: Row[]; documents: Row[];
  documents_done: number; documents_total: number; shipments: R[]; shipment: R; alerts: R[];
  incoterm: R; incoterm_code: string; incoterm_help: R[]; mode: string; erp_error: string; today: string;
};

const OWNER: Record<string, string> = { us: "our desk", carrier: "forwarder / carrier", authority: "chamber / customs" };

/** A date that says how it stands: "in 24 days", "today", "4 days late", or "no date on file". */
function Left({ row }: { row: Row }) {
  if (!row.date) return <span className="ws-small ws-muted">no date</span>;
  const n = row.days_left ?? 0;
  const tone = row.state === "late" ? "var(--ws-bad, #b42318)" : row.state === "today" || row.state === "soon" ? "var(--ws-warn, #b54708)" : "var(--ws-muted, #667085)";
  const text = row.state === "late" ? `${-n} day(s) late` : n === 0 ? "today" : `in ${n} day(s)`;
  return <span className="ws-small" style={{ color: tone, fontWeight: row.state === "late" || row.state === "today" ? 600 : 400 }}>{text}</span>;
}

export function TrackStep({ deal, toast, go, readOnlyGoods }: { deal: R; toast: (m: string, t?: "bad" | "ok") => void; go: (p: string) => void; readOnlyGoods?: boolean }) {
  const [t, setT] = useState<Track | null>(null);
  const put = (v: R) => setT(v as unknown as Track);
  const [busy, setBusy] = useState("");
  const [form, setForm] = useState<R>({});

  const load = async (quiet = false) => {
    if (!quiet) setBusy("load");
    const r = await call("deal_track", { deal_id: deal.id });
    setBusy("");
    if (!r.ok) { toast(r.error || "Could not read the shipping picture.", "bad"); return; }
    put(r);
    setForm(r.shipment || {});
  };
  useEffect(() => { void load(); }, [deal.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const tick = async (row: Row, given: boolean) => {
    setBusy(row.id || row.key);
    const r = await call("deal_track_doc", { deal_id: deal.id, doc: row.id || row.key, given: given ? 1 : 0 });
    setBusy("");
    if (!r.ok) { toast(r.error || "Not saved.", "bad"); return; }
    put(r);
    toast(given ? `${row.label} marked as given.` : `${row.label} un-ticked.`, "ok");
  };
  const saveShip = async () => {
    setBusy("ship");
    const v: R = {};
    for (const k of ["carrier", "awb_number", "tracking_url", "tracking_status", "tracking_status_info", "apparel_forwarder",
      "apparel_booking_no", "apparel_booking_date", "apparel_cutoff", "apparel_etd", "apparel_eta",
      "apparel_on_board_date", "apparel_arrival_date", "apparel_vessel_voyage", "apparel_hbl_no", "apparel_mbl_no"]) {
      if (form[k] !== undefined && String(form[k] ?? "") !== String((t?.shipment || {})[k] ?? "")) v[k] = form[k];
    }
    if (!Object.keys(v).length) { setBusy(""); toast("Nothing changed."); return; }
    const r = await call("deal_track_shipment", { deal_id: deal.id, values: v });
    setBusy("");
    if (!r.ok) { toast(r.error || "The ERP refused it.", "bad"); return; }
    put(r); setForm(r.shipment || {});
    toast("Saved on the ERP's Shipment.", "ok");
  };

  if (!t) return <Card title="Ship & track"><Loading rows={5} /></Card>;
  const ship = t.shipment || {};
  const hasShip = !!ship.name;
  const late = t.documents.filter((d) => d.state === "late" && !d.ticked).length;

  return (
    <>
      <Card title="Ship & track"
        sub={t.contract ? `${t.contract}${t.signed ? " · signed" : " · draft"}${t.mode ? ` · ${t.mode}` : ""}` : "From the contract's own terms"}
        right={<Btn sm kind="plain" busy={busy === "load"} onClick={() => void load()} title="Read the ERP again"><RefreshCw size={13} /> Refresh</Btn>}>
        <div className="ws-grid ws-grid--3">
          <div className="ws-card" style={{ padding: 12 }}>
            <div className="ws-small ws-muted">Papers given</div>
            <div className="ws-kpi__value" style={{ fontSize: 22 }}>{t.documents_done} / {t.documents_total}</div>
          </div>
          <div className="ws-card" style={{ padding: 12 }}>
            <div className="ws-small ws-muted">Papers late</div>
            <div className="ws-kpi__value" style={{ fontSize: 22, color: late ? "var(--ws-bad, #b42318)" : undefined }}>{late}</div>
          </div>
          <div className="ws-card" style={{ padding: 12 }}>
            <div className="ws-small ws-muted">Trade term</div>
            <div className="ws-kpi__value" style={{ fontSize: 22 }}>{t.incoterm_code || "—"}</div>
            <div className="ws-small ws-muted">{t.incoterm?.name || "no Incoterm on the contract"}</div>
          </div>
        </div>
      </Card>

      {t.alerts.length > 0 && <Card title="What needs a person" sub="Read from the contract's own numbers and the ERP's shipment">
        {t.alerts.map((a, i) => <Note key={i} tone={a.tone === "bad" ? "bad" : a.tone === "warn" ? "warn" : undefined}>
          <b>{a.title}</b> — {a.sub}
        </Note>)}
      </Card>}

      <Card title="The four clocks" sub="Every date on the contract, and the money clock derived from the payment terms" flush>
        <div className="ws-table-wrap">
          <table className="ws-table">
            <thead><tr><th>Milestone</th><th>Date</th><th>Standing</th><th>Where the date comes from</th></tr></thead>
            <tbody>{t.schedule.map((r) => (
              <tr key={r.key}>
                <td><b>{r.label}</b></td>
                <td className="ws-nowrap">{r.date ? day(r.date) : <span className="ws-muted">not on the contract</span>}</td>
                <td className="ws-nowrap"><Left row={r} /></td>
                <td className="ws-small ws-muted">{r.basis}</td>
              </tr>))}</tbody>
          </table>
        </div>
        <div className="ws-small ws-muted" style={{ padding: "10px 14px" }}>
          ETD, ETA and the payment date are worked out from the contract's own lead times — change a lead time on the
          Contract tab and these move with it.
        </div>
      </Card>

      <Card title="What we must give the buyer" sub="The papers the contract names, who produces each, and the day it is needed" flush>
        {t.documents.length === 0 ? <Empty title="No documents on the contract" text="The contract's Documents With Shipment line is empty — fill it on the Contract tab so the papers are tracked." /> : (
          <div className="ws-table-wrap">
            <table className="ws-table">
              <thead><tr><th>Paper</th><th>Who</th><th>Needed by</th><th>Standing</th><th style={{ width: 170 }}>Given</th></tr></thead>
              <tbody>{t.documents.map((d) => (
                <tr key={d.id || d.key}>
                  <td><b>{d.label}</b><div className="ws-small ws-muted">{d.basis}</div></td>
                  <td className="ws-small">{OWNER[d.owner || "us"] || d.owner}</td>
                  <td className="ws-nowrap">{d.date ? day(d.date) : <span className="ws-muted">—</span>}</td>
                  <td className="ws-nowrap">{d.ticked ? <span className="ws-small" style={{ color: "var(--ws-ok, #027a48)" }}>given {day(d.given_on)}</span> : <Left row={d} />}</td>
                  <td>
                    {d.ticked
                      ? <Btn sm kind="plain" busy={busy === (d.id || d.key)} onClick={() => void tick(d, false)} title={`Ticked by ${d.given_by || "someone"}`}>Undo</Btn>
                      : <Btn sm busy={busy === (d.id || d.key)} onClick={() => void tick(d, true)}><FileText size={13} /> Mark given</Btn>}
                  </td>
                </tr>))}</tbody>
            </table>
          </div>)}
      </Card>

      <Card title="Where the goods are" sub={hasShip ? `Shipment ${ship.name} in the ERP` : "The ERP has no shipment for this contract yet"}
        right={hasShip && ship.tracking_url ? <Btn sm kind="primary" onClick={() => window.open(ship.tracking_url, "_blank", "noopener")}><ExternalLink size={13} /> Track it</Btn> : undefined}>
        {!hasShip ? (
          <Empty title="Nothing has shipped yet" text={<>In this ERP a Shipment hangs off a <b>Delivery Note</b>: the order is submitted, packed and dispatched first, then the booking, AWB/BL and tracking link are recorded on that Shipment — and they show up here. The schedule and the papers above are tracked already, so nothing is lost while you wait.</>}
            action={<div className="ws-row"><Btn onClick={() => go("orders")}>Order book</Btn><Btn onClick={() => go("tna")}>T&amp;A calendar</Btn></div>} />
        ) : (
          <>
            <dl className="ws-kv">
              <dt>Status</dt><dd>{ship.status || "—"}{ship.ship_status ? ` · ${ship.ship_status}` : ""}</dd>
              <dt>Mode</dt><dd>{ship.mode || t.mode || "—"} {ship.service_type ? `· ${ship.service_type}` : ""}</dd>
              <dt>Forwarder</dt><dd>{ship.forwarder || "—"}</dd>
              <dt>Booking</dt><dd>{ship.booking_no || "—"} {ship.booking_date ? `(${day(ship.booking_date)})` : ""}</dd>
              <dt>Cut-off</dt><dd>{ship.cutoff ? day(ship.cutoff) : "—"}</dd>
              <dt>Route</dt><dd>{[ship.pol, ship.pod, ship.destination].filter(Boolean).join(" → ") || "—"}{ship.vessel_voyage ? ` · ${ship.vessel_voyage}` : ""}</dd>
              <dt>ETD / ETA</dt><dd>{ship.etd ? day(ship.etd) : "—"} / {ship.eta ? day(ship.eta) : "—"}</dd>
              <dt>On board / arrived</dt><dd>{ship.on_board ? day(ship.on_board) : "—"} / {ship.arrival ? day(ship.arrival) : "—"}</dd>
              <dt>Delivered</dt><dd>{ship.delivery ? day(ship.delivery) : "—"}</dd>
              <dt>{ship.bl_type || "B/L"}</dt><dd>{[ship.hbl && `HBL ${ship.hbl}`, ship.mbl && `MBL ${ship.mbl}`, ship.awb && `AWB ${ship.awb}`].filter(Boolean).join(" · ") || "—"}</dd>
              <dt>Carrier</dt><dd>{ship.carrier || "—"}</dd>
              <dt>Tracking</dt><dd>{ship.tracking_status || "—"}{ship.tracking_info ? ` — ${ship.tracking_info}` : ""}</dd>
              <dt>Weight / volume</dt><dd>{[ship.gross_kg && `${ship.gross_kg} kg`, ship.cbm && `${ship.cbm} cbm`].filter(Boolean).join(" · ") || "—"}</dd>
              <dt>Containers</dt><dd>{(ship.containers || []).filter(Boolean).join(", ") || "—"}</dd>
              <dt>Documents on the shipment</dt><dd>{(ship.documents || []).filter(Boolean).join(", ") || "—"}</dd>
            </dl>
            {!readOnlyGoods && <><div className="ws-form" style={{ marginTop: 12 }}>
              <Field label="Carrier"><Input value={form.carrier ?? ""} onChange={(v) => setForm({ ...form, carrier: v })} /></Field>
              <Field label="AWB / BL number"><Input value={form.awb_number ?? ""} onChange={(v) => setForm({ ...form, awb_number: v })} placeholder="e.g. 020-12345678" /></Field>
              <Field label="Tracking link" wide><Input value={form.tracking_url ?? ""} onChange={(v) => setForm({ ...form, tracking_url: v })} placeholder="https://…" /></Field>
              <Field label="Tracking status"><Select value={form.tracking_status ?? ""} onChange={(v) => setForm({ ...form, tracking_status: v })} placeholder="—" options={["", "In Progress", "Delivered", "Returned", "Lost"]} /></Field>
              <Field label="Forwarder"><Input value={form.apparel_forwarder ?? ""} onChange={(v) => setForm({ ...form, apparel_forwarder: v })} /></Field>
              <Field label="Booking no"><Input value={form.apparel_booking_no ?? ""} onChange={(v) => setForm({ ...form, apparel_booking_no: v })} /></Field>
              <Field label="Cut-off"><Input type="date" value={String(form.apparel_cutoff ?? "").slice(0, 10)} onChange={(v) => setForm({ ...form, apparel_cutoff: v })} /></Field>
              <Field label="ETD"><Input type="date" value={String(form.apparel_etd ?? "").slice(0, 10)} onChange={(v) => setForm({ ...form, apparel_etd: v })} /></Field>
              <Field label="ETA"><Input type="date" value={String(form.apparel_eta ?? "").slice(0, 10)} onChange={(v) => setForm({ ...form, apparel_eta: v })} /></Field>
              <Field label="On board"><Input type="date" value={String(form.apparel_on_board_date ?? "").slice(0, 10)} onChange={(v) => setForm({ ...form, apparel_on_board_date: v })} /></Field>
              <Field label="Arrived"><Input type="date" value={String(form.apparel_arrival_date ?? "").slice(0, 10)} onChange={(v) => setForm({ ...form, apparel_arrival_date: v })} /></Field>
            </div>
            <div className="ws-row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
              {ship.tracking_url && <Btn kind="plain" onClick={() => { navigator.clipboard?.writeText(ship.tracking_url).then(() => toast("Tracking link copied.", "ok")).catch(() => toast(ship.tracking_url)); }}><Copy size={13} /> Copy link</Btn>}
              <Btn kind="dark" busy={busy === "ship"} onClick={saveShip}><Truck size={14} /> Save to the ERP</Btn>
            </div></>}
          </>
        )}
      </Card>

      <Card title={`Trade term${t.incoterm_code ? ` — ${t.incoterm_code}` : ""}`} sub="What the Incoterm obliges us to do">
        {t.incoterm?.code ? <>
          <p className="ws-small" style={{ marginTop: 0 }}><b>{t.incoterm.name}.</b> {t.incoterm.meaning}</p>
          <dl className="ws-kv">
            <dt>Risk passes</dt><dd>{t.incoterm.risk}</dd>
            <dt>Freight paid by</dt><dd>{t.incoterm.freight}</dd>
            <dt>Insurance paid by</dt><dd>{t.incoterm.insurance}</dd>
            <dt>Import duty paid by</dt><dd>{t.incoterm.duty}</dd>
            <dt>Makes sense for</dt><dd>{t.incoterm.use_when}</dd>
          </dl>
        </> : <Note tone="warn">No Incoterm on the contract yet. Pick one on the Contract tab — the ERP will not sign without it.</Note>}
        <details style={{ marginTop: 10 }}>
          <summary className="ws-small">All eleven terms, in plain words</summary>
          <div className="ws-table-wrap" style={{ marginTop: 8 }}>
            <table className="ws-table">
              <thead><tr><th>Term</th><th>Means</th><th>Risk passes</th><th>Freight</th><th>Insurance</th><th>Duty</th><th>Mode</th></tr></thead>
              <tbody>{t.incoterm_help.map((x: R) => (
                <tr key={x.code} style={x.code === t.incoterm_code ? { background: "var(--ws-tint, #f4f6fb)" } : undefined}>
                  <td className="ws-nowrap"><b>{x.code}</b></td><td className="ws-small">{x.meaning}</td>
                  <td className="ws-small">{x.risk}</td><td className="ws-small">{x.freight}</td>
                  <td className="ws-small">{x.insurance}</td><td className="ws-small">{x.duty}</td><td className="ws-small">{x.modes}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </details>
      </Card>

      {t.erp_error && <Note tone="warn">The ERP did not answer, so its own shipment facts are not shown: {t.erp_error}</Note>}
    </>
  );
}

export default TrackStep;
