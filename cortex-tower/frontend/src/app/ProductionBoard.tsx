import { Badge, Btn, Card, Empty, Head, Kpi, Loading, Note, day, num, useCall } from "./kit";
import type { R } from "./kit";

/* The production board (ORDER_TO_SHIP_PLAN section 7): every order with a live Production Card, its stage totals from the Production Movement ledger,
   the sewn percentage and today's output. It replaces the Cortex WIP screen, which reads an older evidence model that is not on the Arinox site. */
export function ProductionBoard({ go }: { go: (p: string) => void }) {
  const r = useCall("production_board_get", {}, []);
  const d: R | undefined = r.data || undefined;
  if (r.loading && !d) return <div className="ws-page"><Loading rows={5} /></div>;
  if (!d) return <div className="ws-page"><Note tone="bad">{r.error || "The production board could not be read."}</Note></div>;
  const rows: R[] = d.rows || [], stages: R[] = d.stages || [], t: R = d.totals || {};
  return (
    <div className="ws-page">
      <Head title="Production board" sub="Orders with a production card. From the production ledger; click an order to open its cut and sew step." acts={<Btn sm onClick={() => r.reload(true)}>Refresh</Btn>} />
      <div className="ws-grid ws-grid--kpi ws-mb">
        <Kpi label="Orders in production" value={num(rows.length)} /><Kpi label="Order quantity" value={num(t.order_qty)} /><Kpi label="Sewn" value={num(t.sewn)} hint={t.order_qty ? `${num((t.sewn / t.order_qty) * 100, 1)}% of the quantity` : undefined} />
        <Kpi label="Sewn today" value={num(t.today_sewn)} />
      </div>
      <Card title="Orders" flush>
        {rows.length === 0 ? <Empty title="No production card yet" text="Make a production card on an order's cut and sew step; the order then appears here." /> : (
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Production board" style={{ minWidth: 820 }}>
            <thead><tr><th>Order</th><th>Styles</th><th>Ex-factory</th><th className="num">Order</th>{stages.map((s) => <th key={s.key} className="num">{s.label}</th>)}<th className="num">Sewn %</th><th className="num">Today</th></tr></thead>
            <tbody>{rows.map((x) => (
              <tr key={x.sales_order} className="is-click" onClick={() => go(`orders/${encodeURIComponent(x.sales_order)}/cutsew`)}>
                <td><b className="ws-small">{x.sales_order}</b></td><td className="ws-small">{(x.styles || []).join(", ")}</td><td className="ws-small">{x.ex_factory_date ? day(x.ex_factory_date) : "—"}</td>
                <td className="num">{num(x.order_qty)}</td>{stages.map((s) => <td key={s.key} className="num">{num(x[s.key])}</td>)}
                <td className="num"><Badge tone={x.sewn_pct >= 100 ? "ok" : x.sewn_pct > 0 ? "info" : undefined}>{num(x.sewn_pct, 0)}%</Badge></td><td className="num">{num(x.today_sewn)}</td></tr>))}</tbody></table></div>)}
      </Card>
    </div>
  );
}
