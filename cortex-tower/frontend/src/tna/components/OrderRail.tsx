import { useMemo, useState } from "react";
import { Search, Star, PanelLeftClose } from "lucide-react";
import { fmtDate } from "../lib/format";
import type { Rag, TnaOrder } from "../types";

/**
 * OrderRail — the left-hand order list. Picking an order is like working an inbox:
 * one row per order with buyer, style, ship date and a RAG dot. Replaces the v1
 * top-bar order dropdown.
 */
export default function OrderRail({
  orders, orderId, onSelect, ragByOrder, collapsed, onClose,
}: {
  orders: TnaOrder[];
  orderId: string;
  onSelect: (id: string) => void;
  ragByOrder?: Record<string, Rag>;
  collapsed?: boolean;
  onClose?: () => void;
}) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return orders;
    return orders.filter((o) =>
      `${o.order_id} ${o.customer} ${o.style_no} ${o.style_name}`.toLowerCase().includes(s));
  }, [orders, q]);

  if (collapsed) return null;

  return (
    <aside className="order-rail" aria-label="Orders">
      <div className="order-rail-head">
        <span className="eyebrow">Orders</span>
        <span className="rail-head-right">
          <span className="pill-count">{orders.length}</span>
          {onClose && (
            <button className="rail-close" onClick={onClose} title="Hide orders panel" aria-label="Hide orders panel">
              <PanelLeftClose size={15} />
            </button>
          )}
        </span>
      </div>
      <div className="order-rail-search">
        <Search size={14} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search order, buyer, style…"
          aria-label="Search orders"
        />
      </div>
      <div className="order-rail-list">
        {filtered.length === 0 && <div className="muted" style={{ padding: 12, fontSize: 13 }}>No matching orders.</div>}
        {filtered.map((o) => {
          const rag = ragByOrder?.[o.order_id];
          return (
            <button
              key={o.order_id}
              className={`order-item${o.order_id === orderId ? " active" : ""}`}
              onClick={() => onSelect(o.order_id)}
            >
              <span className={`rag-dot rag-${rag || "grey"}`} />
              <span className="order-item-main">
                <span className="order-item-top">
                  <span className="order-item-buyer">{o.customer || "—"}</span>
                  <span className="order-item-ship mono">{fmtDate(o.ship_date)}</span>
                </span>
                <span className="order-item-style">{o.style_no || "—"}{o.style_name ? ` · ${o.style_name}` : ""}</span>
                <span className="order-item-id mono">{o.order_id}</span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="order-rail-foot muted">
        <Star size={12} /> TnA runs backwards from each ship date
      </div>
    </aside>
  );
}
