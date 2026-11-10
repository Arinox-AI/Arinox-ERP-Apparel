import type { ReactNode } from "react";
import RagPill from "./RagPill";
import { fmtDate, fmtInt, fmtMoney, DASH } from "../lib/format";
import type { TnaHeader } from "../types";

function Fact({ label, value, mono, big }: { label: string; value: ReactNode; mono?: boolean; big?: boolean }) {
  return (
    <div className="hs-fact">
      <div className="hs-fact-label">{label}</div>
      <div className={`hs-fact-value${big ? " lg" : ""}${mono ? " mono" : ""}`}>{value}</div>
    </div>
  );
}

export default function HeaderStrip({ header }: { header: TnaHeader }) {
  const dts = header.days_to_ship;
  return (
    <section className="card">
      <div className="header-strip">
        <div className="hs-facts">
          <Fact label="Order" value={header.order_id} mono />
          <Fact label="Buyer" value={<>{header.customer || DASH}{header.customer_legal ? <span className="muted" style={{ fontSize: 12 }}> · {header.customer_legal}</span> : null}</>} />
          <Fact label="Style" value={<>{header.style_no || DASH}<span className="muted" style={{ fontSize: 12 }}> · {header.style_name || DASH}</span></>} />
          <Fact label="Colour" value={header.colour || DASH} mono />
          <Fact label="Qty (pcs)" value={fmtInt(header.qty)} mono big />
          <Fact label="PO no" value={header.po_no || DASH} mono />
          <Fact label="Order value" value={fmtMoney(header.order_value, header.currency)} mono />
          <Fact label="Ship date (anchor)" value={fmtDate(header.ship_date)} mono />
          <Fact label="Company" value={<span style={{ fontSize: 13 }}>{header.company || DASH}</span>} />
          <Fact label="Order status" value={<span className="badge">{header.sales_order_status || DASH}</span>} />
        </div>
        <div className="hs-rag">
          <div className="hs-fact-label">Days to ship</div>
          <div className={`hs-days ${dts < 0 ? "neg" : "pos"}`}>{dts > 0 ? `+${dts}` : dts}</div>
          <div className="muted" style={{ fontSize: 11 }}>working days from as-of</div>
          <div style={{ marginTop: 6 }}><RagPill rag={header.rag} label={header.overall_status} /></div>
        </div>
      </div>
    </section>
  );
}
