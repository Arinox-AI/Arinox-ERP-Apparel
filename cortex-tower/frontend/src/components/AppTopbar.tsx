import { Sparkles } from "lucide-react";
import type { View } from "../types";

const TITLES: Record<View, { title: string; sub: string }> = {
  wip: {
    title: "WIP plan — Gantt & calendar",
    sub: "Every milestone of every size SKU in the window it owns, live from Cortex WIP — read it as bars, not as a table",
  },
  tna: {
    title: "Time & Action (TnA) Calendar",
    sub: "Backward-planned milestones from the ship date — 61 milestones per order, live from the ERP",
  },
  overview: {
    title: "Operations overview",
    sub: "Live position across the order book, manufacturing, sourcing, quality and shipping",
  },
  orders: {
    title: "Order book",
    sub: "Every live Sales Order (SO) in KOGO ERP, with its buyer Purchase Order (PO), style, value and promised delivery",
  },
  risks: {
    title: "Risks requiring action",
    sub: "Derived in real time from ERP signals — open any risk for the full evidence",
  },
  actions: {
    title: "Recommended actions",
    sub: "KOGO's next-best actions — previewed, then executed as reversible ERP drafts",
  },
  operations: {
    title: "Operational views",
    sub: "Order book, production, quality, shipments and sourcing — live aggregates",
  },
  forecast: {
    title: "Forecast",
    sub: "Delivery risk, stock cover, margin and cash projected from the live ERP position",
  },
  fabric: {
    title: "Fabric price check",
    sub: "Four sources compared style by style — what the BOM says, what costing says, what we ordered and what we pay — and every place they disagree",
  },
  activity: {
    title: "Activity & audit",
    sub: "Every decision taken in this dashboard, newest first",
  },
  mail: {
    title: "Outbound mail",
    sub: "Approve, edit or reject grounded emails before they are sent",
  },
  intake: {
    title: "Order intake",
    sub: "The mailbox, read and understood — every document becomes a reviewed decision before any ERP record exists",
  },
  enquiries: {
    title: "Buyer enquiries",
    sub: "Every buyer asking for a price, and what the ERP already holds for each style — the cost sheet, the BOM, the pack and the price we last sold it at",
  },
  inbox: {
    title: "Inbox",
    sub: "Incoming mail read and understood — new orders, revised POs and invoices, matched to your live orders",
  },
};

export function AppTopbar(props: { view: View; onAsk: () => void; criticalCount: number }) {
  const { view, onAsk, criticalCount } = props;
  const t = TITLES[view];
  return (
    <header className="topbar">
      <div className="topbar__inner">
        <div className="topbar__heading">
          <div className="topbar__title">{t.title}</div>
          <div className="topbar__sub">{t.sub}</div>
        </div>
        <div className="topbar__tools">
          {criticalCount > 0 && !["intake", "enquiries", "inbox", "mail", "activity"].includes(view) && (
            <span className="badge badge--critical"><span className="badge__dot" />{criticalCount} critical risk{criticalCount > 1 ? "s" : ""}</span>
          )}
          <button className="btn btn--primary" onClick={onAsk}>
            <Sparkles size={14} />
            Ask KOGO
          </button>
        </div>
      </div>
    </header>
  );
}
