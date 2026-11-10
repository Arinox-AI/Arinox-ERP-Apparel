import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Package,
  Search,
} from "lucide-react";
import { Card, Empty } from "../ui";
import { fmtDate, fmtNum } from "../types";

type SortKey = "delivery_date" | "grand_total" | "packed_pct" | "sent_pct" | "quantity" | "order_number";

/* Full forms for the trade abbreviations shown on an order — so nobody has to google them. */
const INCOTERM_FULL: Record<string, string> = {
  DDP: "Delivered Duty Paid",
  DAP: "Delivered At Place",
  DPU: "Delivered at Place Unloaded",
  EXW: "Ex Works",
  FCA: "Free Carrier",
  FAS: "Free Alongside Ship",
  FOB: "Free On Board",
  CFR: "Cost & Freight",
  CIF: "Cost, Insurance & Freight",
  CPT: "Carriage Paid To",
  CIP: "Carriage & Insurance Paid To",
};
const incotermFull = (c?: string) => (c ? INCOTERM_FULL[c.toUpperCase()] || "" : "");

/* Ordered-vs-quantity bar. Over 100% is an over-ship, shown in amber. */
function PackedBar({ ordered, packed, pct, exact = true }: { ordered: number; packed: number; pct: number; exact?: boolean }) {
  const over = pct > 100;
  const width = Math.max(0, Math.min(100, pct));
  const color = over ? "var(--warning)" : pct >= 95 ? "var(--positive)" : "var(--chart-1)";
  return (
    <div style={{ minWidth: 132 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: over ? "var(--warning-ink)" : "var(--text-primary)" }}>
          {!exact && <span style={{ color: "var(--text-muted)", fontWeight: 400 }} title="Estimated from style-level evidence">≈ </span>}
          {fmtNum(packed)}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>/ {fmtNum(ordered)}</span>
        <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 700, color }}>{pct}%</span>
      </div>
      <div style={{ height: 6, borderRadius: 999, background: "var(--surface-sunken)", marginTop: 5, overflow: "hidden" }}>
        <div style={{ width: `${width}%`, height: "100%", background: color, borderRadius: 999 }} />
      </div>
    </div>
  );
}

function TermsBlock({ o }: { o: any }) {
  const has = !!o.has_terms;
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <FileText size={14} color="var(--text-muted)" />
        <span style={{ fontSize: 12.5, fontWeight: 700 }}>Terms &amp; conditions</span>
        {has ? (
          <span className="badge badge--positive"><CheckCircle2 size={10} /> on order</span>
        ) : (
          <span className="badge badge--warning"><AlertTriangle size={10} /> none recorded</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {o.incoterm && (
          <span className="badge badge--brand"
                title="Incoterm = International Commercial Terms. The trade rule that decides who pays freight, insurance and import duties.">
            Incoterm: {o.incoterm}{incotermFull(o.incoterm) ? ` — ${incotermFull(o.incoterm)}` : ""}
          </span>
        )}
        {o.payment_terms && (
          <span className="badge badge--outline" title="Payment terms template — the credit / due-date terms on the order.">
            Payment terms: {o.payment_terms}
          </span>
        )}
        {o.advance_payment_status && (
          <span className="badge badge--outline" title="Whether a deposit / advance payment was asked from the customer before shipping.">
            Advance payment: {o.advance_payment_status}
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
        <b>Incoterm</b> = International Commercial Terms (who pays freight, insurance &amp; import duties) ·{" "}
        <b>DDP</b> = Delivered Duty Paid (seller pays everything, incl. import duty) ·{" "}
        <b>Advance payment</b> = deposit requested before shipping.
      </div>

      {o.source_terms && (
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
          <b>Source terms:</b> {o.source_terms}
        </div>
      )}

      {o.terms_text ? (
        <div
          style={{
            background: "var(--surface-sunken)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: "10px 12px",
            fontSize: 12.5,
            lineHeight: 1.55,
            color: "var(--text-secondary)",
            whiteSpace: "pre-wrap",
          }}
        >
          {o.terms_text}
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
          No terms text is recorded on this order in the ERP. Open the Sales Order to add it.
        </div>
      )}
    </div>
  );
}

export function OrdersView(props: { orders: any[] }) {
  const { orders } = props;
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [company, setCompany] = useState("");
  const [month, setMonth] = useState("");
  const [sort, setSort] = useState<SortKey>("delivery_date");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [open, setOpen] = useState<string | null>(null);
  const [termsOnly, setTermsOnly] = useState(false);

  const statuses = useMemo(() => Array.from(new Set(orders.map((o) => o.status).filter(Boolean))), [orders]);
  const companies = useMemo(() => Array.from(new Set(orders.map((o) => o.company).filter(Boolean))), [orders]);
  const months = useMemo(
    () => Array.from(new Set(orders.map((o) => String(o.delivery_date || "").slice(0, 7)).filter(Boolean))).sort(),
    [orders]
  );

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = orders
      .filter((o) => (status === "all" ? true : o.status === status))
      .filter((o) => (company ? o.company === company : true))
      .filter((o) => (month ? String(o.delivery_date || "").startsWith(month) : true))
      .filter((o) => (termsOnly ? !!o.has_terms : true))
      .filter((o) => (needle ? JSON.stringify(o).toLowerCase().includes(needle) : true));
    const val = (o: any) => {
      if (sort === "grand_total") return Number(o.grand_total) || 0;
      if (sort === "packed_pct") return Number(o.packed_pct) || 0;
      if (sort === "sent_pct") return Number(o.sent_pct) || 0;
      if (sort === "quantity") return Number(o.quantity) || 0;
      return String(o[sort] || "");
    };
    out.sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      const c = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return dir === "asc" ? c : -c;
    });
    return out;
  }, [orders, q, status, company, month, termsOnly, sort, dir]);

  const filtered = !!(company || month || status !== "all" || q.trim() || termsOnly);

  const totalValue = rows.reduce((s, o) => s + (Number(o.grand_total) || 0), 0);
  const totalPoBasis = rows.reduce((s, o) => s + (Number(o.order_basis_usd) || 0), 0);
  const totalQty = rows.reduce((s, o) => s + (Number(o.quantity) || 0), 0);
  const totalSent = rows.reduce((s, o) => s + (Number(o.sent_qty) || 0), 0);
  const missingTerms = rows.filter((o) => !o.has_terms).length;

  /* The AUTHORITATIVE shipped figure is the final packing list / commercial
   * invoice (o.sent_qty). If a shipment record names the order it is exact; if
   * there is no shipment evidence at all we fall back to the factory packed
   * figure, clearly marked as such. */
  const sentOf = (o: any) => {
    const known = !!o.sent_source && o.sent_source !== "none";
    return {
      known,
      ordered: Number(o.planned_qty || o.quantity || 0),
      qty: known ? Number(o.sent_qty || 0) : Number(o.packed_qty || 0),
      pct: known ? Number(o.sent_pct || 0) : Number(o.packed_pct || 0),
      exact: known ? !!o.sent_exact : !!o.packed_exact,
    };
  };

  const sortBtn = (key: SortKey, label: string) => (
    <th
      key={label}
      onClick={() => {
        if (sort === key) setDir(dir === "asc" ? "desc" : "asc");
        else { setSort(key); setDir("asc"); }
      }}
      style={{
        textAlign: "left", padding: "10px 14px", fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: "0.5px", whiteSpace: "nowrap", cursor: "pointer",
        borderBottom: "1px solid var(--border)", userSelect: "none",
      }}
      title="Click to sort"
    >
      {label}{sort === key ? (dir === "asc" ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <>
      {/* filters — sticky so the search never scrolls away */}
      <div
        style={{
          display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12,
          position: "sticky", top: 0, zIndex: 5, background: "var(--surface)", padding: "10px 0",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div className="tabs">
          <button className={`tab${status === "all" ? " is-active" : ""}`} onClick={() => setStatus("all")}>
            All <span style={{ marginLeft: 6, color: "var(--text-muted)", fontWeight: 700 }}>{orders.length}</span>
          </button>
          {statuses.map((s) => (
            <button key={s} className={`tab${status === s ? " is-active" : ""}`} onClick={() => setStatus(s)}>{s}</button>
          ))}
        </div>

        <select className="select" value={company} onChange={(e) => setCompany(e.target.value)} title="Filter by company">
          <option value="">All companies</option>
          {companies.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>

        <select className="select" value={month} onChange={(e) => setMonth(e.target.value)} title="Filter by delivery month">
          <option value="">All delivery months</option>
          {months.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>

        <select className="select" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} title="Sort by">
          <option value="delivery_date">Sort: delivery date</option>
          <option value="grand_total">Sort: order value</option>
          <option value="sent_pct">Sort: sent %</option>
          <option value="packed_pct">Sort: factory packed %</option>
          <option value="quantity">Sort: quantity</option>
          <option value="order_number">Sort: order number</option>
        </select>

        <button
          className={`btn btn--sm${termsOnly ? " btn--brand" : ""}`}
          onClick={() => setTermsOnly((v) => !v)}
          title="Show only orders that carry terms & conditions"
        >
          <FileText size={12} /> Terms {missingTerms > 0 ? `(${rows.length - missingTerms}/${rows.length})` : ""}
        </button>

        {filtered && (
          <button className="btn btn--sm btn--ghost" onClick={() => { setStatus("all"); setCompany(""); setMonth(""); setQ(""); setTermsOnly(false); }}>
            Clear filters
          </button>
        )}

        <div style={{ marginLeft: "auto", position: "relative" }}>
          <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }} />
          <input
            className="input"
            style={{ paddingLeft: 30, minWidth: 250 }}
            placeholder="Search order (SO), PO, style…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>

      {/* Plain-language note so "SO" / "PO" are never a mystery */}
      <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 14, lineHeight: 1.5 }}>
        <b>SO</b> = Sales Order (Cortex's order in KOGO ERP) ·{" "}
        <b>PO</b> = the buyer's Purchase Order (the source document in Drive).{" "}
        Values below are the <b>Sales Order</b> values — if an order was amended after the PO, the two can differ.
      </div>

      <div className="metrics" style={{ marginBottom: 16 }}>
        <div className="metric">
          <span className="metric__rail" style={{ background: "var(--chart-1)" }} />
          <div className="metric__label">Orders shown</div>
          <div className="metric__value">{rows.length}</div>
        </div>
        <div
          className="metric"
          title={[
            "Sales Orders currently carry the SHIPPED quantity (incl. tolerance).",
            `Sales Order basis = USD ${fmtNum(Math.round(totalValue))}`,
            `PO / order basis  = USD ${fmtNum(Math.round(totalPoBasis))}`,
            "Cortex (Oct 2026): the Sales Order quantity should reflect the PO/order quantity, and the commercial-invoice quantity (shipped) is the basis for delivery & invoicing.",
            "To be applied from the next cycle.",
          ].join("\n")}
        >
          <span className="metric__rail" style={{ background: "var(--positive)" }} />
          <div className="metric__label">Order book (PO/order basis)</div>
          <div className="metric__value" style={{ color: "var(--positive)" }}>
            {fmtNum(Math.round(totalPoBasis))}<span className="metric__unit">USD</span>
          </div>
          <div className="metric__foot">ERP Sales Orders {fmtNum(Math.round(totalValue))} USD</div>
        </div>
        <div className="metric">
          <span className="metric__rail" style={{ background: "var(--chart-3)" }} />
          <div className="metric__label">Units shown</div>
          <div className="metric__value">{fmtNum(totalQty)}<span className="metric__unit">pcs</span></div>
        </div>
        <div className="metric" title="Shipped quantity taken from the final packing list / commercial invoice — the authoritative 'sent' figure.">
          <span className="metric__rail" style={{ background: totalSent >= totalQty ? "var(--positive)" : "var(--warning)" }} />
          <div className="metric__label">Sent to date</div>
          <div className="metric__value">{fmtNum(totalSent)}<span className="metric__unit">pcs</span></div>
        </div>
        {missingTerms > 0 && (
          <div className="metric">
            <span className="metric__rail" style={{ background: "var(--warning)" }} />
            <div className="metric__label">Orders with no terms</div>
            <div className="metric__value" style={{ color: "var(--warning-ink)" }}>{missingTerms}</div>
          </div>
        )}
      </div>

      <Card flush>
        {rows.length === 0 ? (
          <Empty icon={<Package size={18} />} title="No orders match" hint="Adjust the filter or search." />
        ) : (
          <div style={{ maxHeight: "70vh", overflow: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5, minWidth: 1020 }}>
              <thead>
                <tr style={{ background: "var(--surface-hover)", position: "sticky", top: 0, zIndex: 2 }}>
                  <th style={{ width: 30, borderBottom: "1px solid var(--border)" }} />
                  {sortBtn("order_number", "Order")}
                  <th style={{ textAlign: "left", padding: "10px 14px", fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", borderBottom: "1px solid var(--border)" }}>Buyer</th>
                  <th style={{ textAlign: "left", padding: "10px 14px", fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", borderBottom: "1px solid var(--border)" }} title="PO = the buyer's Purchase Order (the source document in Drive)">PO (buyer)</th>
                  {sortBtn("quantity", "Qty")}
                  {sortBtn("grand_total", "Value (USD)")}
                  {sortBtn("delivery_date", "Delivery")}
                  {sortBtn("sent_pct", "Ordered vs sent")}
                  <th style={{ textAlign: "left", padding: "10px 14px", fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", borderBottom: "1px solid var(--border)" }}>Terms</th>
                  <th style={{ textAlign: "left", padding: "10px 14px", fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", borderBottom: "1px solid var(--border)" }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => {
                  const isOpen = open === o.id;
                  const sf = sentOf(o);
                  return (
                    <React.Fragment key={o.id}>
                      <tr
                        onClick={() => setOpen(isOpen ? null : o.id)}
                        style={{ borderBottom: "1px solid var(--border)", cursor: "pointer", background: isOpen ? "var(--surface-hover)" : undefined }}
                      >
                        <td style={{ padding: "10px 6px 10px 12px", color: "var(--text-muted)" }}>
                          {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </td>
                        <td style={{ padding: "10px 14px", fontWeight: 600, whiteSpace: "nowrap", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11.5 }}>
                          {o.order_number}
                          {o.is_sample && (
                            <span className="badge badge--warning" style={{ marginLeft: 6 }} title={o.source_exception || "Customer photo sample"}>Photo sample</span>
                          )}
                        </td>
                        <td style={{ padding: "10px 14px", color: "var(--text-secondary)" }}>{o.buyer_name}</td>
                        <td style={{ padding: "10px 14px", color: "var(--text-secondary)" }}>{o.po_no || "—"}</td>
                        <td style={{ padding: "10px 14px", whiteSpace: "nowrap" }}>{fmtNum(o.quantity)}</td>
                        <td style={{ padding: "10px 14px", whiteSpace: "nowrap", fontWeight: 600 }}>{fmtNum(o.grand_total)}</td>
                        <td style={{ padding: "10px 14px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>{fmtDate(o.delivery_date)}</td>
                        <td style={{ padding: "10px 14px" }}>
                          <PackedBar ordered={sf.ordered} packed={sf.qty} pct={sf.pct} exact={sf.exact} />
                        </td>
                        <td style={{ padding: "10px 14px", whiteSpace: "nowrap" }}>
                          {o.has_terms ? (
                            <span className="badge badge--positive" title={o.incoterm ? `${o.incoterm} — ${incotermFull(o.incoterm) || "Incoterm"} (International Commercial Terms)` : "Terms on order"}>
                              <CheckCircle2 size={10} /> {o.incoterm || "on order"}
                            </span>
                          ) : (
                            <span className="badge badge--warning"><AlertTriangle size={10} /> none</span>
                          )}
                        </td>
                        <td style={{ padding: "10px 14px", whiteSpace: "nowrap" }}>
                          <span className={`badge badge--${o.status === "Overdue" ? "critical" : "warning"}`}>{o.status}</span>
                        </td>
                      </tr>

                      {isOpen && (
                        <tr style={{ borderBottom: "1px solid var(--border)", background: "var(--surface-hover)" }}>
                          <td colSpan={10} style={{ padding: "6px 18px 18px 42px" }}>
                            <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 1fr) minmax(320px, 1.4fr)", gap: 22 }}>
                              <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
                                <div style={{ fontSize: 12.5, fontWeight: 700 }}>Ordered vs sent (final packing list / invoice)</div>
                                <PackedBar ordered={sf.ordered} packed={sf.qty} pct={sf.pct} exact={sf.exact} />
                                <div className="kv" style={{ fontSize: 12.5 }}>
                                  <div className="kv__k">Ordered (PO / SO)</div><div className="kv__v">{fmtNum(o.quantity)} pcs</div>
                                  <div className="kv__k">Sent (final packing list / invoice)</div><div className="kv__v">{sf.known ? `${fmtNum(o.sent_qty)} pcs` : "no shipment evidence"}</div>
                                  <div className="kv__k" title="The production tracker's own figure — internal and unverified; it is NOT what was sent.">Factory packed (unverified)</div><div className="kv__v">{fmtNum(o.packed_qty)} pcs{!o.packed_exact ? " (est.)" : ""}</div>
                                  <div className="kv__k">Delivered so far</div><div className="kv__v">{o.per_delivered ?? 0}%</div>
                                  <div className="kv__k">Value</div><div className="kv__v">USD {fmtNum(o.grand_total)}</div>
                                  <div className="kv__k">Styles</div><div className="kv__v">{(o.styles || []).join(", ") || "—"}</div>
                                </div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
                                  <b>Sent</b> comes from the final packing list / commercial invoice — the source of truth for what left the factory. The factory packed figure is internal and unverified.
                                </div>
                                {!sf.known && (
                                  <div className="banner banner--warning" style={{ fontSize: 12.5 }}>
                                    <AlertTriangle size={14} /> <b>No shipment evidence</b> — no packing list / invoice names this order, so the factory packed figure is shown instead.
                                  </div>
                                )}
                                {sf.known && !sf.exact && (
                                  <div className="banner banner--warning" style={{ fontSize: 12.5 }}>
                                    <AlertTriangle size={14} /> <b>Estimated</b> — the shipment records don't name this order, so sent is summed from its style(s) and may be shared with another order of the same style.
                                  </div>
                                )}
                                {sf.known && sf.pct > 100 && (
                                  <div className="banner banner--warning" style={{ fontSize: 12.5 }}>
                                    <AlertTriangle size={14} /> Sent exceeds ordered ({sf.pct}%) — the over-shipment needs commercial approval.
                                  </div>
                                )}
                              </div>
                              <div>
                                <TermsBlock o={o} />
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
