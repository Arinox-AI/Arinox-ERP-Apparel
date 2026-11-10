import { AlertCircle, Briefcase, Clock, FileText, Inbox as InboxIcon, Package, Receipt, Truck } from "lucide-react";
import { Badge, Bars, Btn, Card, Empty, Head, Kpi, Loading, Note, StageBadge, money, num, short, useCall } from "./kit";
import type { R } from "./kit";

function ccyText(m?: R): string {
  if (!m) return "—";
  const ks = Object.keys(m).filter((k) => Number(m[k]));
  if (!ks.length) return "0";
  return ks.map((k) => `${k} ${short(Number(m[k]))}`).join(" · ");
}

export function Dashboard({ go, me }: { go: (p: string) => void; me: R }) {
  const r = useCall("deal_dashboard", {}, []);
  const d = r.data || {};
  const erp: R = d.erp || {};
  const inbox: R = d.inbox || {};
  const stages: R[] = (d.stages || []).filter((s: R) => s.stage !== "lost");
  const maxN = Math.max(1, ...stages.map((s) => s.count));
  const hello = (me.name || me.email || "").split(/[ @]/)[0];

  return (
    <div className="ws-page">
      <Head title={`Good ${new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening"}${hello ? ", " + hello : ""}`}
        sub="What came in, what is waiting on you, and where every order stands."
        acts={<><Btn onClick={() => go("inbox")}><InboxIcon size={15} /> Inbox</Btn><Btn kind="primary" onClick={() => go("deals")}><Briefcase size={15} /> Deals</Btn></>} />
      {r.loading && !r.data ? <Loading rows={5} /> : r.error ? <Note tone="bad">{r.error}</Note> : (
        <>
          <div className="ws-grid ws-grid--kpi">
            <Kpi label="Need a reply" icon={<InboxIcon size={14} />} value={num(inbox.needs_reply || 0)} hint={`${num(inbox.inquiry || 0)} inquir${inbox.inquiry === 1 ? "y" : "ies"} in the inbox`} tone={inbox.needs_reply ? "warn" : undefined} onClick={() => go("inbox")} />
            <Kpi label="Open deals" icon={<Briefcase size={14} />} value={num(d.open || 0)} hint={d.open_value ? `${money(d.open_value, "USD", 0)} quoted` : "inquiry → accepted"} onClick={() => go("deals")} />
            <Kpi label="Win rate" icon={<FileText size={14} />} value={d.win_rate === null || d.win_rate === undefined ? "—" : `${d.win_rate}%`} hint="contracts ÷ (contracts + lost)" />
            <Kpi label="Open sales orders" icon={<Package size={14} />} value={erp.orders_error ? "—" : num(erp.open_orders || 0)} hint={erp.orders_error ? "ERP not reachable" : ccyText(erp.open_value)} onClick={() => go("orders")} />
            <Kpi label="Due in 30 days" icon={<Truck size={14} />} value={erp.orders_error ? "—" : num((erp.due_30 || []).length)} hint="by Sales Order delivery date" tone={(erp.due_30 || []).some((x: R) => x.days < 0) ? "bad" : undefined} />
            <Kpi label="Receivables" icon={<Receipt size={14} />} value={erp.receivables_error ? "—" : ccyText(erp.receivables)} hint={erp.receivables_error ? "ERP not reachable" : `${num(erp.receivable_count || 0)} unpaid invoices`} />
          </div>
          {(d.erp_error || erp.orders_error) && <div className="ws-mt"><Note tone="warn">Order figures are missing because the ERP did not answer. Deals and the inbox still work. <span className="ws-small" style={{ opacity: 0.75 }}>({d.erp_error || erp.orders_error})</span></Note></div>}

          <div className="ws-grid ws-grid--2 ws-mt">
            <Card title="Pipeline" sub="Deals by stage" right={<Btn sm kind="plain" onClick={() => go("deals")}>Open board</Btn>}>
              {stages.every((s) => !s.count) ? <Empty title="No deals yet" text="Start one from an inquiry in the Inbox." /> : (
                <div className="ws-funnel">
                  {stages.map((s) => (
                    <div key={s.stage} className="ws-funnel__col" onClick={() => go("deals")} title={`${s.label}: ${s.count} deal(s), ${num(s.qty)} pcs`}>
                      <div className="ws-funnel__n">{s.count}</div>
                      <div className="ws-funnel__bar" style={{ height: `${Math.max(4, (s.count / maxN) * 92)}px`, background: s.stage === "order" ? "#16a34a" : s.stage === "contract" ? "#1e293b" : undefined }} />
                      <div className="ws-funnel__l">{s.label}</div>
                    </div>))}
                </div>)}
            </Card>
            <Card title="Waiting on you" sub="Buyers who answered, customers to link">
              {(d.needs_us || []).length === 0 ? <div className="ws-small ws-muted">Nothing is waiting on you.</div> : (
                <div style={{ margin: -16 }}>{d.needs_us.map((x: R) => (
                  <div key={x.id} className="ws-list-row" onClick={() => go(`deals/${x.id}`)}>
                    <AlertCircle size={15} color="var(--ws-warn)" />
                    <div style={{ minWidth: 0, flex: 1 }}><b className="ws-ellipsis" style={{ display: "block" }}>{x.customer || x.title}</b><span className="ws-small ws-muted">{x.text}</span></div>
                    <Badge tone={x.kind === "buyer_replied" ? "warn" : undefined}>{x.kind === "buyer_replied" ? "Buyer replied" : "Action"}</Badge>
                  </div>))}</div>)}
            </Card>
          </div>

          <div className="ws-grid ws-grid--3 ws-mt">
            <Card title="Quotes waiting on the buyer">
              {(d.waiting_on_buyer || []).length === 0 ? <div className="ws-small ws-muted">No quote is waiting.</div> : (
                <div style={{ margin: -16 }}>{d.waiting_on_buyer.map((x: R) => (
                  <div key={x.id} className="ws-list-row" onClick={() => go(`deals/${x.id}`)}>
                    <Clock size={14} color={x.days > 7 ? "var(--ws-bad)" : "var(--ws-faint)"} />
                    <span className="ws-ellipsis" style={{ flex: 1 }}>{x.customer || x.title}</span>
                    <span className="ws-small" style={{ color: x.days > 7 ? "var(--ws-bad)" : "var(--ws-muted)" }}>{x.days} d</span>
                  </div>))}</div>)}
            </Card>
            <Card title="Inquiries not quoted yet">
              {(d.aging || []).length === 0 ? <div className="ws-small ws-muted">Every inquiry is quoted.</div> : (
                <div style={{ margin: -16 }}>{d.aging.map((x: R) => (
                  <div key={x.id} className="ws-list-row" onClick={() => go(`deals/${x.id}`)}>
                    <StageBadge stage={x.stage} label={x.stage} /><span className="ws-ellipsis" style={{ flex: 1 }}>{x.customer || x.title}</span><span className="ws-small ws-muted">{x.days} d</span>
                  </div>))}</div>)}
            </Card>
            <Card title="Top customers" sub="Open + won deal value">
              <Bars rows={(d.top_customers || []).map((c: R) => ({ label: c.customer, value: Number(c.value || 0) }))} fmt={(v) => short(v)} />
            </Card>
          </div>

          <div className="ws-grid ws-grid--2 ws-mt">
            <Card title="Orders due in the next 30 days" flush right={<Btn sm kind="plain" onClick={() => go("orders")}>All orders</Btn>}>
              {(erp.due_30 || []).length === 0 ? <div className="ws-small ws-muted" style={{ padding: 16 }}>{erp.orders_error ? "ERP not reachable." : "No order is due in the next 30 days."}</div> : (
                <table className="ws-table"><thead><tr><th>Order</th><th>Customer</th><th className="num">Value</th><th className="num">Due</th></tr></thead>
                  <tbody>{erp.due_30.map((s: R) => (
                    <tr key={s.name}><td><b>{s.name}</b></td><td className="ws-ellipsis" style={{ maxWidth: 200 }}>{s.customer}</td><td className="num">{money(s.grand_total, s.currency, 0)}</td>
                      <td className="num" style={{ color: s.days < 0 ? "var(--ws-bad)" : undefined }}>{s.days < 0 ? `${-s.days} d late` : s.days === 0 ? "today" : `${s.days} d`}</td></tr>))}</tbody></table>)}
            </Card>
            <Card title="Sales orders by month" sub="Last 12 months, from the ERP">
              {(erp.orders_by_month || []).length === 0 ? <div className="ws-small ws-muted">No orders yet.</div> : (
                <>
                  <div className="ws-spark">{erp.orders_by_month.map((m: R) => {
                    const mx = Math.max(1, ...erp.orders_by_month.map((x: R) => x.count));
                    return <div key={m.month} style={{ height: `${(m.count / mx) * 100}%` }} title={`${m.month}: ${m.count}`} />;
                  })}</div>
                  <div className="ws-row ws-row--between ws-small ws-muted ws-mt-s"><span>{erp.orders_by_month[0]?.month}</span><span>{erp.orders_by_month[erp.orders_by_month.length - 1]?.month}</span></div>
                </>)}
            </Card>
          </div>

          <Card className="ws-mt" title="Inbox" right={<Btn sm kind="plain" onClick={() => go("inbox")}>Open</Btn>}>
            <div className="ws-grid ws-grid--kpi">
              {[["inquiry", "Inquiries"], ["orders", "Orders & amendments"], ["money", "Invoices & payments"], ["questions", "Questions"], ["needs_reply", "Need a reply"]].map(([k, l]) => (
                <div key={k} className="ws-card ws-kpi is-click" onClick={() => go("inbox")}><div className="ws-kpi__label">{l}</div><div className="ws-kpi__value" style={{ fontSize: 20 }}>{num(inbox[k] || 0)}</div></div>))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
