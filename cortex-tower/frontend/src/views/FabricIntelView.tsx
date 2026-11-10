import { useMemo, useState, type CSSProperties } from "react";
import { AlertTriangle, Coins, Info, RefreshCw } from "lucide-react";
import type { FabricFlag, FabricIntel, FabricRow } from "../types";
import { FABRIC_FLAG_LABEL, VERDICT } from "../types";
import { Card, Drawer, Empty, KV, PageSection, Skel } from "../ui";
import { HBar, HGroupedBar, Donut } from "../charts";

/* Full-width card — the charts a customer reads need the whole row. */
const WIDE: CSSProperties = { gridColumn: "1 / -1" };

const money = (v: any, dp = 2) =>
  v === null || v === undefined || v === "" ? "—" : `$${Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const num = (v: any, dp = 3) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const pct = (v: any, dp = 1) =>
  v === null || v === undefined || v === "" ? "—" : `${Number(v).toFixed(dp)}%`;

const SEV_ICON: Record<string, any> = { critical: AlertTriangle, warning: AlertTriangle, info: Info };
const SEV_CLS: Record<string, string> = { critical: "badge--critical", warning: "badge--warning", info: "badge--outline" };

/* Column headers written as a question, with a plain-English explanation on hover. */
const COLS: { key: string; tip: string }[] = [
  { key: "Style", tip: "The style (garment) this order is for." },
  { key: "Fabric used", tip: "The fabric the bill of materials says this style consumes." },
  { key: "Ordered", tip: "Pieces ordered on the live sales orders." },
  { key: "BOM says (yd/pc)", tip: "Yard of fabric per garment, taken from the ERP bill of materials (the master)." },
  { key: "Costing says (yd/pc)", tip: "Yard of fabric per garment, from INTERNAL COSTING.xlsx (the quote)." },
  { key: "They differ by", tip: "How far apart the sources are. Median is used as the middle value; +/-5% is a warning, +/-15% critical." },
  { key: "We pay ($/yd)", tip: "The rate we actually bought at, converted to USD per yard from the purchase order." },
  { key: "Cost ($/pc)", tip: "Total costed cost of one garment: fabric + cut & make + trims + wash + overheads." },
  { key: "Sold at ($/pc)", tip: "The price on the live sales order." },
  { key: "Margin", tip: "Selling price minus cost, as a percentage of the selling price." },
  { key: "Fabric needed ($)", tip: "Total fabric required for the order, valued at the rate we pay." },
  { key: "What's wrong", tip: "Every check that failed for this style." },
];

function Verdict({ v }: { v: string }) {
  const m = VERDICT[v] || VERDICT.watch;
  return <span className={`badge ${m.cls}`}>{m.label}</span>;
}

function Flags({ code, limit }: { code: string[]; limit?: number }) {
  const list = (code || []).slice(0, limit ?? 9);
  if (!list.length) return <span style={{ color: "var(--text-muted)" }}>Nothing found</span>;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {list.map((c) => <span key={c} className="badge badge--outline" style={{ fontSize: 10.5 }}>{FABRIC_FLAG_LABEL[c] || c}</span>)}
    </div>
  );
}

export function FabricIntelView(props: { data: FabricIntel | null; loading: boolean; onRefresh: () => void }) {
  const { data, loading, onRefresh } = props;
  const [open, setOpen] = useState<FabricRow | null>(null);
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<"all" | "flagged">("all");

  const rows = useMemo(() => {
    const all = data?.rows || [];
    const needle = q.trim().toLowerCase();
    return all
      .filter((r) => (only === "flagged" ? r.verdict !== "ok" : true))
      .filter((r) => (needle ? JSON.stringify(r).toLowerCase().includes(needle) : true));
  }, [data, q, only]);

  if (loading && !data) {
    return (
      <>
        <Skel h={190} r={12} />
        <div className="metrics" style={{ marginTop: 18 }}>{Array.from({ length: 6 }).map((_, i) => <Skel key={i} h={104} r={12} />)}</div>
        <div className="grid-charts" style={{ marginTop: 22 }}>{Array.from({ length: 4 }).map((_, i) => <Skel key={i} h={250} r={12} />)}</div>
      </>
    );
  }

  if (!data || data.live === false) {
    return (
      <Card>
        <Empty
          icon={<Coins size={18} />}
          title="Fabric intelligence unavailable"
          hint={data?.error || data?.connection?.error || "The ERP did not answer — nothing is shown rather than a guess."}
        />
        <div style={{ display: "flex", justifyContent: "center", paddingBottom: 18 }}>
          <button className="btn btn--sm" onClick={onRefresh}><RefreshCw size={13} /> Retry</button>
        </div>
      </Card>
    );
  }

  const s = data.summary || {};
  const c = data.charts || ({} as any);
  const flags: FabricFlag[] = data.flags || [];
  const rank: Record<string, number> = { critical: 0, warning: 1, info: 2 };
  const topFlags = [...flags].sort((a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3)).slice(0, 6);

  const openFlags = open ? flags.filter((f) => f.style === open.style) : [];
  const tile = (label: string, value: React.ReactNode, hint: string, colour: string, valueColour?: string) => (
    <div className="metric">
      <span className="metric__rail" style={{ background: colour }} />
      <div className="metric__label">{label}</div>
      <div className="metric__value" style={{ color: valueColour || "var(--text)" }}>{value}</div>
      <div className="metric__foot">{hint}</div>
    </div>
  );

  return (
    <>
      <PageSection
        title="The position in numbers"
        hint="Whole order book, costed from the same four sources. A style is Alert if any check is critical, Watch if any is a warning. Fabric figures warn at ±5% and go critical at ±15%; price at ±5%; margin floor 15%."
      >
        <div className="metrics">
          {tile("Styles in the order book", s.styles ?? 0,
                s.order_qty_pcs ? `${Number(s.order_qty_pcs).toLocaleString()} pieces` : "", "var(--chart-1)")}
          {tile("Styles you should look at", (s.styles_alert || 0) + (s.styles_watch || 0),
                `${s.styles_alert || 0} alert · ${s.styles_watch || 0} watch · ${s.styles_ok || 0} ok`,
                (s.styles_alert || 0) > 0 ? "var(--negative)" : "var(--positive)",
                (s.styles_alert || 0) > 0 ? "var(--negative)" : "var(--positive)")}
          {tile("Styles where the fabric figures disagree", s.consumption_conflicts ?? 0,
                "BOM vs costing vs buyer PO", "var(--warning)", "var(--warning)")}
          {tile("Styles where the fabric price moved", s.rate_drifts ?? 0,
                "bought ≠ quoted rate", "var(--chart-6)")}
          {tile("Fabric we must buy", money(s.fabric_exposure_usd, 0),
                "fabric required × rate we pay", "var(--chart-5)")}
          {tile("Average margin", pct(s.blended_margin_pct),
                `${money(s.order_value_usd, 0)} order book · cost ${money(s.cost_of_goods_usd, 0)}`,
                "var(--positive)", "var(--positive)")}
        </div>
      </PageSection>

      <PageSection
        title="What the numbers look like"
        hint="Every chart compares the same sources. Hover a bar for the exact figure."
      >
        <div className="grid-charts">
          <Card
            style={WIDE}
            title="How much fabric does one garment use?"
            sub="Yard per piece, as each of the three documents states it — a wide gap means the documents disagree"
          >
            <HGroupedBar
              data={c.consumption_sources || []}
              series={[
                { key: "bom", label: "Bill of materials (ERP)", color: "var(--chart-1)" },
                { key: "costing", label: "Internal costing sheet", color: "var(--chart-3)" },
                { key: "client_po", label: "Buyer's purchase order", color: "var(--chart-2)" },
              ]}
              rowLabel={(d) => String(d.x)}
              valueFmt={(v) => `${v.toFixed(3)} yd`}
              labelWidth={132}
            />
          </Card>

          <Card
            style={WIDE}
            title="What each garment costs, and what we sell it for"
            sub="USD per piece — cost is fabric at the rate we pay, plus cut &amp; make, trims, wash and overheads"
          >
            <HGroupedBar
              data={c.cost_vs_price || []}
              series={[
                { key: "cost", label: "Cost per garment", color: "var(--chart-4)" },
                { key: "price", label: "Sold for", color: "var(--chart-2)" },
              ]}
              rowLabel={(d) => String(d.x)}
              valueFmt={(v) => `$${v.toFixed(2)}`}
              labelWidth={132}
            />
          </Card>

          <Card title="How much fabric each style needs" sub="USD — the fabric the order needs at the rate we pay">
            <HBar
              data={(c.fabric_value_by_style || []).map((d: any) => ({ x: String(d.x), y: Number(d.y) || 0 }))}
              color="var(--chart-5)"
              valueFmt={(v) => `$${Math.round(v).toLocaleString()}`}
              labelWidth={128}
            />
          </Card>

          <Card title="What got flagged, and why" sub="One row per check that failed">
            <Donut data={(c.flags_by_type || []).map((d: any) => ({ x: String(d.x), y: Number(d.y) || 0 }))} />
          </Card>
        </div>
      </PageSection>

      <PageSection title="Things you should decide on" hint="Most serious first — each one names the style it came from">
        <Card flush>
          {topFlags.length === 0 ? (
            <Empty good title="Nothing flagged" hint="The fabric figures, the cost and the price all agree." />
          ) : (
            <div>
              {topFlags.map((f, i) => {
                const Icon = SEV_ICON[f.severity] || Info;
                return (
                  <div className="row" key={`${f.style}-${f.type}-${i}`}>
                    <span className="row__rail" style={{ background: f.severity === "critical" ? "var(--negative)" : f.severity === "warning" ? "var(--warning)" : "var(--chart-5)" }} />
                    <div className="row__main">
                      <div className="row__title">{f.title} <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>— style {f.style}</span></div>
                      <div className="row__meta">
                        <span><Icon size={11} style={{ verticalAlign: -1, marginRight: 4 }} />{FABRIC_FLAG_LABEL[f.type] || f.type}</span>
                        <span>{f.detail}</span>
                        {f.impact_usd ? <b style={{ color: "var(--negative)" }}>≈ {money(Math.abs(f.impact_usd), 0)} at risk</b> : null}
                      </div>
                    </div>
                    <span className={`badge ${SEV_CLS[f.severity] || "badge--outline"}`}>{f.severity}</span>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </PageSection>

      <PageSection
        title="Every style, one row each"
        hint="Hover a column heading to see what it means · click a row for the full working"
        actions={
          <>
            <div className="tabs">
              <button className={`tab${only === "all" ? " is-active" : ""}`} onClick={() => setOnly("all")}>
                All <span style={{ marginLeft: 6, color: "var(--text-muted)", fontWeight: 700 }}>{(data.rows || []).length}</span>
              </button>
              <button className={`tab${only === "flagged" ? " is-active" : ""}`} onClick={() => setOnly("flagged")}>
                Needs attention <span style={{ marginLeft: 6, color: "var(--text-muted)", fontWeight: 700 }}>{(data.rows || []).filter((r) => r.verdict !== "ok").length}</span>
              </button>
            </div>
            <input className="input" style={{ minWidth: 210 }} placeholder="Search style, fabric, vendor…" value={q} onChange={(e) => setQ(e.target.value)} />
          </>
        }
      >
        <Card flush>
          {rows.length === 0 ? (
            <Empty title="Nothing matches" hint="Adjust the filter or search." />
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5, minWidth: 1240 }}>
                <thead>
                  <tr style={{ background: "var(--surface-hover)" }}>
                    {COLS.map((h) => (
                      <th key={h.key} title={h.tip} style={{ textAlign: "left", padding: "11px 14px", fontSize: 10.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", whiteSpace: "nowrap", borderBottom: "1px solid var(--border)", cursor: "help" }}>{h.key}</th>
                    ))}
                    <th style={{ borderBottom: "1px solid var(--border)" }} />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const cyd = r.consumption_yd || ({} as any);
                    const spread = cyd.spread_pct;
                    return (
                      <tr key={r.style} className="row--click" style={{ borderBottom: "1px solid var(--border)" }} onClick={() => setOpen(r)}>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap" }}>
                          <div style={{ fontWeight: 600, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11.5 }}>{r.style}</div>
                          <div style={{ color: "var(--text-muted)", fontSize: 11 }}>{r.description || "—"}</div>
                        </td>
                        <td style={{ padding: "11px 14px", color: "var(--text-secondary)", whiteSpace: "nowrap", fontSize: 11.5 }}>{r.fabric_item || "—"}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap" }}>{r.order_qty_pcs ? Number(r.order_qty_pcs).toLocaleString() : "—"}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap" }}>{num(cyd.bom)}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap" }}>{num(cyd.costing)}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap", fontWeight: 600, color: spread == null ? "var(--text-muted)" : spread > 15 ? "var(--negative)" : spread > 5 ? "var(--warning)" : "var(--positive)" }}>
                          {spread == null ? "—" : `±${Number(spread).toFixed(1)}%`}
                        </td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap" }}>{money(r.rate_usd?.buy_per_yd)}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap" }}>{money(r.cost_usd?.reference)}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap", fontWeight: 600 }}>{money(r.sell_price_usd)}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap", fontWeight: 600, color: (r.margin_pct || 0) < 15 ? "var(--warning)" : "var(--positive)" }}>{pct(r.margin_pct)}</td>
                        <td style={{ padding: "11px 14px", whiteSpace: "nowrap" }}>{money(r.fabric_exposure_usd, 0)}</td>
                        <td style={{ padding: "11px 14px", maxWidth: 190 }}><Flags code={r.flags} limit={2} /></td>
                        <td style={{ padding: "11px 14px" }}><Verdict v={r.verdict} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </PageSection>

      {open && (
        <Drawer
          onClose={() => setOpen(null)}
          title={open.style}
          sub={`${open.description || "Style"} · ${open.fabric_item || "no fabric item"}${open.vendor ? " · " + open.vendor : ""}`}
          footer={<span className="badge badge--outline">{open.flags.length} thing{open.flags.length === 1 ? "" : "s"} to look at</span>}
        >
          <div style={{ marginBottom: 14 }}><Verdict v={open.verdict} /></div>

          <div className="card__title" style={{ marginBottom: 8 }}>The order</div>
          <KV items={[
            { k: "Client PO", v: (open.client_po_numbers || []).join(", ") || "—" },
            { k: "Sales orders", v: (open.sales_orders || []).join(", ") || "—" },
            { k: "Ordered", v: open.order_qty_pcs ? `${Number(open.order_qty_pcs).toLocaleString()} pieces` : "—" },
            { k: "Order value", v: money(open.order_value_usd, 0) },
            { k: "Fabric content", v: open.fabric_content || "—" },
            { k: "GSM", v: open.gsm || "—" },
          ]} />

          <div className="card__title" style={{ margin: "18px 0 8px" }}>How much fabric a garment uses (yard)</div>
          <KV items={[
            { k: "BOM says", v: num(open.consumption_yd?.bom) },
            { k: "Internal costing says", v: num(open.consumption_yd?.costing) },
            { k: "Costing +3% wastage", v: num(open.consumption_yd?.costing_with_3pct) },
            { k: "Buyer's PO says", v: num(open.consumption_yd?.client_po) },
            { k: "Middle value used", v: <b>{num(open.consumption_yd?.consensus)}</b> },
            { k: "They differ by", v: open.consumption_yd?.spread_pct == null ? "—" : `±${Number(open.consumption_yd.spread_pct).toFixed(1)}%` },
          ]} />

          <div className="card__title" style={{ margin: "18px 0 8px" }}>How much fabric the order needs</div>
          <KV items={[
            { k: "Per garment (BOM)", v: `${num(open.required_m_unit?.bom)} m` },
            { k: "Whole order (BOM)", v: `${num(open.required_m_total?.bom, 1)} m` },
            { k: "Whole order (costing)", v: `${num(open.required_m_total?.costing, 1)} m` },
            { k: "Whole order (+3% wastage)", v: `${num(open.required_m_total?.with_3pct, 1)} m` },
            { k: "Fabric needed, valued", v: <b>{money(open.fabric_exposure_usd, 0)}</b> },
          ]} />

          <div className="card__title" style={{ margin: "18px 0 8px" }}>Price</div>
          <KV items={[
            { k: "We pay", v: open.rate_usd?.buy_per_yd ? `${money(open.rate_usd.buy_per_yd)} / yard (${money(open.rate_usd.buy_per_m)} / m)` : "never purchased" },
            { k: "We were quoted", v: open.rate_usd?.quoted_per_yd ? `${money(open.rate_usd.quoted_per_yd)} / yard` : "—" },
            { k: "Bought on", v: open.rate_usd?.po || "—" },
            { k: "From", v: open.rate_usd?.supplier || "—" },
          ]} />

          <div className="card__title" style={{ margin: "18px 0 8px" }}>What one garment costs (USD)</div>
          <KV items={[
            { k: "Fabric at BOM usage", v: money(open.cost_usd?.fabric_bom_basis) },
            { k: "Fabric at costing usage", v: money(open.cost_usd?.fabric_costing_basis) },
            { k: "Cut & make", v: money(open.cost_usd?.cm) },
            { k: "Trims", v: money(open.cost_usd?.trim) },
            { k: "Washing", v: money(open.cost_usd?.wash) },
            { k: "Overheads", v: money(open.cost_usd?.overhead) },
            { k: "Rejection", v: money(open.cost_usd?.rejection) },
            { k: "Finance", v: money(open.cost_usd?.finance) },
            { k: "Depreciation", v: money(open.cost_usd?.depreciation) },
            { k: "Total on BOM usage", v: <b>{money(open.cost_usd?.bom_basis_total)}</b> },
            { k: "Total on costing usage", v: <b>{money(open.cost_usd?.costing_basis_total)}</b> },
            { k: "Cost we use", v: <b>{money(open.cost_usd?.reference)}</b> },
            { k: "We sell at", v: money(open.sell_price_usd) },
            { k: "Client PO price", v: money(open.client_po_price_usd) },
            { k: "Margin", v: <b style={{ color: (open.margin_pct || 0) < 15 ? "var(--warning)" : "var(--positive)" }}>{money(open.margin_usd)} per piece · {pct(open.margin_pct)}</b> },
          ]} />

          {openFlags.length > 0 && (
            <>
              <div className="card__title" style={{ margin: "18px 0 8px" }}>What we found on this style</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {openFlags.map((f, i) => (
                  <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                    <span className={`badge ${SEV_CLS[f.severity] || "badge--outline"}`}>{f.severity}</span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600 }}>{f.title}</div>
                      <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{f.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Drawer>
      )}
    </>
  );
}
