import RagPill from "./RagPill";
import { fmtDate, fmtInt, DASH } from "../lib/format";
import type { ProgramOrder } from "../types";

function ragDot(rag: string) {
  const c = rag === "red" ? "var(--error)" : rag === "amber" ? "var(--warning)" : "var(--success)";
  return <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 4, background: c }} />;
}

export default function ProgramTable({
  orders, onOpen,
}: {
  orders: ProgramOrder[];
  onOpen: (orderId: string) => void;
}) {
  if (!orders.length) {
    return <div className="empty"><div className="empty-title">No orders</div><div>No in-scope orders were returned.</div></div>;
  }
  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>Order</th>
            <th>Buyer</th>
            <th>Style</th>
            <th className="right">Qty</th>
            <th>Ship date</th>
            <th className="right">Days to ship</th>
            <th className="right">Overdue</th>
            <th className="right">Progress</th>
            <th className="right">ERP-linked</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.order_id} className="clickable" onClick={() => onOpen(o.order_id)} title="Open this order's TnA">
              <td className="mono" style={{ fontWeight: 500 }}>{o.order_id}</td>
              <td style={{ fontSize: 12 }}>{o.customer || DASH}</td>
              <td className="mono" style={{ fontSize: 12 }}>{o.style_no || DASH}</td>
              <td className="right mono">{fmtInt(o.qty)}</td>
              <td className="date">{fmtDate(o.ship_date)}</td>
              <td className="right mono" style={{ color: (o.days_to_ship ?? 0) < 0 ? "var(--error)" : undefined }}>
                {o.days_to_ship ?? DASH}
              </td>
              <td className="right mono" style={{ color: o.overdue_count ? "var(--error)" : undefined }}>{o.overdue_count}</td>
              <td className="right mono">{Math.round(o.progress_pct)}%</td>
              <td className="right mono muted">{o.erp_linked_count}</td>
              <td><div className="row" style={{ gap: 6 }}>{ragDot(o.rag)}<RagPill rag={o.rag} label={o.overall_status} /></div></td>
              <td className="right"><span className="badge badge-mono">open ▸</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
