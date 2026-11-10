import { useState } from "react";
import { ArrowLeft, Plus } from "lucide-react";
import { Btn, Card, Empty, Head, Loading, Modal, Note, StageBadge, day, money, num, useCall } from "./kit";
import type { R } from "./kit";
import { CustomerPicker } from "./CustomerPicker";
import { useCx } from "../cx/ui";

export function Customers({ go, name }: { go: (p: string) => void; name?: string }) {
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const r = useCall("customer_list", { q, limit: 200 }, []);
  if (name) return <CustomerDetail name={name} go={go} />;
  const rows: R[] = r.data?.customers || [];
  return (
    <div className="ws-page">
      <Head title="Customers" sub="Buyers in the ERP. Open one to see their deals, contracts and orders."
        acts={<><input className="ws-input" style={{ width: 240 }} placeholder="Search customers" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search customers" />
          <Btn kind="primary" onClick={() => setAdding(true)}><Plus size={15} /> New customer</Btn></>} />
      {r.loading && !r.data ? <Loading /> : r.error ? <Note tone="bad">{r.error}</Note> : rows.length === 0 ? (
        <div className="ws-card"><Empty title={q ? "No customer by that name" : "No customers yet"} action={<Btn kind="primary" onClick={() => setAdding(true)}>Add a customer</Btn>} /></div>
      ) : (
        <div className="ws-card ws-table-wrap">
          <table className="ws-table"><thead><tr><th>Customer</th><th>Currency</th><th>Territory</th><th>Group</th></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.name} className="is-click" onClick={() => go(`customers/${encodeURIComponent(c.name)}`)}>
                <td><b>{c.customer_name || c.name}</b></td><td>{c.default_currency || "—"}</td><td>{c.territory || "—"}</td><td>{c.customer_group || "—"}</td></tr>))}</tbody></table>
        </div>)}
      {adding && <Modal title="New customer" onClose={() => setAdding(false)}>
        <CustomerPicker onPicked={(c) => { setAdding(false); void r.reload(true); go(`customers/${encodeURIComponent(c)}`); }} />
      </Modal>}
    </div>
  );
}

function CustomerDetail({ name, go }: { name: string; go: (p: string) => void }) {
  const cx = useCx();
  const r = useCall("customer_overview", { customer: name }, []);
  const d = r.data || {};
  return (
    <div className="ws-page">
      <div style={{ marginBottom: 8 }}><Btn kind="plain" sm onClick={() => go("customers")}><ArrowLeft size={14} /> Customers</Btn></div>
      <Head title={name} acts={<Btn onClick={() => cx?.openDoc?.("Customer", name)}>Open in records</Btn>} />
      {r.loading && !r.data ? <Loading /> : r.error ? <Note tone="bad">{r.error}</Note> : (
        <div className="ws-grid ws-grid--3">
          <Card title={`Deals (${(d.deals || []).length})`} flush>
            {(d.deals || []).length === 0 ? <div className="ws-small ws-muted" style={{ padding: 14 }}>No deals in the tower.</div> : d.deals.map((x: R) => (
              <div key={x.id} className="ws-list-row" onClick={() => go(`deals/${x.id}`)}><StageBadge stage={x.stage} label={x.stage_label} /><span className="ws-ellipsis" style={{ flex: 1 }}>{x.title}</span><span className="ws-small ws-muted">{num(x.total_qty)} pcs</span></div>))}
          </Card>
          <Card title={`Contracts (${(d.contracts || []).length})`} flush>
            {(d.contracts || []).length === 0 ? <div className="ws-small ws-muted" style={{ padding: 14 }}>None.</div> : d.contracts.map((x: R) => (
              <div key={x.name} className="ws-list-row" onClick={() => cx?.openDoc?.("Sales Contract", x.name)}><b className="ws-small" style={{ flex: 1 }}>{x.name}</b><span className="ws-small ws-muted">{x.status} · {day(x.contract_date)}</span></div>))}
          </Card>
          <Card title={`Sales orders (${(d.orders || []).length})`} flush>
            {d.orders_error && <div style={{ padding: 14 }}><Note tone="warn">{d.orders_error}</Note></div>}
            {(d.orders || []).length === 0 ? <div className="ws-small ws-muted" style={{ padding: 14 }}>None.</div> : d.orders.map((x: R) => (
              <div key={x.name} className="ws-list-row" onClick={() => cx?.openDoc?.("Sales Order", x.name)}><b className="ws-small" style={{ flex: 1 }}>{x.name}</b><span className="ws-small ws-muted">{x.status} · {money(x.grand_total, x.currency, 0)}</span></div>))}
          </Card>
        </div>)}
    </div>
  );
}
