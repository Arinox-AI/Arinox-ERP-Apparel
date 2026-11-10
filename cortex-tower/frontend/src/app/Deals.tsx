import { useState } from "react";
import { AlertCircle, LayoutGrid, List as ListIcon, Plus } from "lucide-react";
import { Btn, Empty, Field, Head, Input, Loading, Modal, Note, StageBadge, call, money, num, useCall, useToast, when } from "./kit";
import type { R } from "./kit";
import { CustomerPicker } from "./CustomerPicker";

/* five columns fit a laptop screen; each card still shows its exact stage */
const COLS = [
  { k: "inquiry", l: "Inquiry", stages: ["inquiry"] }, { k: "costing", l: "Costing", stages: ["costing"] },
  { k: "quoted", l: "Quoted", stages: ["quoted", "negotiating"] }, { k: "contract", l: "Agreed / contract", stages: ["accepted", "contract"] },
  { k: "order", l: "Ordered", stages: ["order"] },
];

export function Deals({ go }: { go: (p: string) => void }) {
  const [view, setView] = useState<"board" | "list">(() => { try { return (localStorage.getItem("ws_deals_view") as "board" | "list") || "board"; } catch { return "board"; } });
  const [q, setQ] = useState("");
  const [showLost, setShowLost] = useState(false);
  const [creating, setCreating] = useState(false);
  const r = useCall("deal_list", {}, []);
  const all: R[] = r.data?.deals || [];
  const deals = all.filter((d) => !q || JSON.stringify([d.title, d.customer_name, d.styles.map((s: R) => s.style_no)]).toLowerCase().includes(q.toLowerCase()));
  const setV = (v: "board" | "list") => { setView(v); try { localStorage.setItem("ws_deals_view", v); } catch { /* */ } };

  return (
    <div className="ws-page">
      <Head title="Deals" sub="Every buyer inquiry, from the first mail to the Sales Order. Open one to cost it, quote it, record the buyer's answer and make the contract."
        acts={<>
          <input className="ws-input" style={{ width: 220 }} placeholder="Search deals, styles, customers" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search deals" />
          <Btn icon title="Board" kind={view === "board" ? "dark" : "ghost"} onClick={() => setV("board")}><LayoutGrid size={15} /></Btn>
          <Btn icon title="List" kind={view === "list" ? "dark" : "ghost"} onClick={() => setV("list")}><ListIcon size={15} /></Btn>
          <Btn kind="primary" onClick={() => setCreating(true)}><Plus size={15} /> New deal</Btn>
        </>} />
      {r.loading && !r.data ? <Loading /> : r.error ? <Note tone="bad">{r.error}</Note> : all.length === 0 ? (
        <div className="ws-card"><Empty title="No deals yet" text="Open an inquiry in the Inbox and press “Start a deal from this mail”, or create one by hand."
          action={<div className="ws-row" style={{ justifyContent: "center" }}><Btn kind="primary" onClick={() => go("inbox")}>Go to the Inbox</Btn><Btn onClick={() => setCreating(true)}>New deal</Btn></div>} /></div>
      ) : view === "board" ? (
        <>
          <div className="ws-board">
            {COLS.map((c) => {
              const ds = deals.filter((d) => c.stages.includes(d.stage));
              const value = ds.reduce((a, d) => a + Number(d.total_value || 0), 0);
              return (
                <div key={c.k} className="ws-col">
                  <div className="ws-col__head"><StageBadge stage={c.k} label={c.l} /><span>{ds.length}</span><span className="ws-muted">{value ? money(value, "", 0) : ""}</span></div>
                  {ds.map((d) => <DealCard key={d.id} d={d} onOpen={() => go(`deals/${d.id}`)} />)}
                  {!ds.length && <div className="ws-small ws-muted" style={{ padding: "6px 4px" }}>—</div>}
                </div>
              );
            })}
          </div>
          <div className="ws-mt"><Btn kind="plain" sm onClick={() => setShowLost(!showLost)}>{showLost ? "Hide" : "Show"} lost deals ({all.filter((d) => d.stage === "lost").length})</Btn></div>
          {showLost && <div className="ws-mt-s"><DealTable deals={deals.filter((d) => d.stage === "lost")} go={go} /></div>}
        </>
      ) : <DealTable deals={deals} go={go} />}
      {creating && <NewDeal onClose={() => setCreating(false)} onMade={(id) => go(`deals/${id}`)} />}
    </div>
  );
}

function DealCard({ d, onOpen }: { d: R; onOpen: () => void }) {
  return (
    <button className="ws-dcard" onClick={onOpen}>
      <div className="ws-row ws-row--between" style={{ marginBottom: 4 }}>
        <StageBadge stage={d.stage} label={d.stage_label} />
        {d.attention && <span className="ws-flag"><AlertCircle size={12} /> {d.attention.kind === "buyer_replied" ? "Buyer replied" : "Needs you"}</span>}
      </div>
      <b>{d.customer_name || "No customer yet"}</b>
      <div className="ws-small ws-muted ws-ellipsis">{d.title}</div>
      <div className="ws-small ws-mt-s">{d.styles.filter((s: R) => s.status !== "dropped").map((s: R) => s.style_no).join(", ") || "No styles"}</div>
      <div className="ws-dcard__foot"><span>{num(d.total_qty)} pcs</span><span className="ws-mono">{d.total_value ? money(d.total_value, d.currency) : ""}</span></div>
      <div className="ws-small ws-muted ws-mt-s" style={{ lineHeight: 1.35 }}>{d.next?.text}</div>
    </button>
  );
}

function DealTable({ deals, go }: { deals: R[]; go: (p: string) => void }) {
  return (
    <div className="ws-card ws-table-wrap">
      <table className="ws-table">
        <thead><tr><th>Customer</th><th>Deal</th><th>Stage</th><th>Styles</th><th className="num">Qty</th><th className="num">Value</th><th>Next</th><th>Updated</th></tr></thead>
        <tbody>{deals.map((d) => (
          <tr key={d.id} className="is-click" onClick={() => go(`deals/${d.id}`)}>
            <td><b>{d.customer_name || "—"}</b></td><td className="ws-ellipsis" style={{ maxWidth: 260 }}>{d.title}</td>
            <td><StageBadge stage={d.stage} label={d.stage_label} /></td><td>{d.styles.length}</td>
            <td className="num">{num(d.total_qty)}</td><td className="num">{d.total_value ? money(d.total_value, d.currency) : "—"}</td>
            <td className="ws-small" style={{ maxWidth: 260 }}>{d.attention ? <span className="ws-flag">{d.attention.text}</span> : d.next?.text}</td>
            <td className="ws-small ws-muted ws-nowrap">{when(d.updated_at)}</td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

function NewDeal({ onClose, onMade }: { onClose: () => void; onMade: (id: number) => void }) {
  const toast = useToast();
  const [customer, setCustomer] = useState("");
  const [title, setTitle] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const make = async () => {
    setBusy(true);
    const r = await call("deal_create", { customer, title, contact_email: email });
    setBusy(false);
    if (!r.ok) { toast(r.error || "Not created.", "bad"); return; }
    onMade(r.deal.id);
  };
  return (
    <Modal title="New deal" sub="For an inquiry that came by phone, WhatsApp or a visit. Inquiries by mail start from the Inbox." onClose={onClose}
      foot={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={!title.trim()} onClick={make}>Create</Btn></>}>
      <div style={{ display: "grid", gap: 12 }}>
        <Field label="What is it?"><Input value={title} onChange={setTitle} placeholder="e.g. Fall 2027 — 4 woven shirts" autoFocus /></Field>
        <Field label="Buyer e-mail" hint="The quote is sent here, and their reply comes back into the deal."><Input value={email} onChange={setEmail} placeholder="buyer@company.com" /></Field>
        <Field label="Customer"><CustomerPicker value={customer} email={email} onPicked={(c) => setCustomer(c)} compact /></Field>
      </div>
    </Modal>
  );
}
