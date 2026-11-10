import type { Dashboard } from "../types";
import { Card, Empty, PageSection } from "../ui";

function money(n: any) {
  const v = Number(n);
  if (!isFinite(v)) return String(n ?? "—");
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function num(n: any) {
  const v = Number(n);
  return isFinite(v) ? v.toLocaleString("en-US") : String(n ?? "—");
}
function pct(n: any) {
  const v = Number(n);
  return isFinite(v) ? `${v}%` : "—";
}

const TH: React.CSSProperties = { textAlign: "left", fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)", padding: "6px 10px", borderBottom: "1px solid var(--border)" };
const TD: React.CSSProperties = { fontSize: 12.5, padding: "7px 10px", borderBottom: "1px solid var(--border)" };

function Verdict({ v }: { v?: string }) {
  const map: Record<string, string> = {
    healthy: "badge--positive", reliable: "badge--positive", covered: "badge--positive", on_track: "badge--positive",
    thin: "badge--warning", watch: "badge--warning", tight: "badge--warning", at_risk: "badge--warning",
    negative: "badge--critical", at_risk2: "badge--critical", short: "badge--critical", will_miss: "badge--critical",
  };
  const cls = map[v || ""] || "badge--outline";
  return <span className={`badge ${cls}`} style={{ textTransform: "capitalize" }}>{v ? v.replace(/_/g, " ") : "—"}</span>;
}

export function ForecastView({ dash }: { dash: Dashboard }) {
  const f = dash.forecast;
  const cash = f?.cash?.by_currency || {};
  const ccys = Object.keys(cash);

  return (
    <>
      <PageSection title="Cash position (kept per currency)" hint={f?.cash?.note}>
        {ccys.length === 0 ? (
          <Empty title="No outstanding balances" hint="No receivables or payables currently open." />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(ccys.length, 3)}, minmax(240px, 1fr))`, gap: 14 }}>
            {ccys.map((c) => {
              const e = cash[c];
              return (
                <Card key={c} title={c} sub="Receivables vs payables">
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <tbody>
                      <tr><td style={TD}>Receivables</td><td style={{ ...TD, textAlign: "right" }}>{money(e.receivables)}</td></tr>
                      <tr><td style={TD}>Overdue</td><td style={{ ...TD, textAlign: "right", color: e.overdue_receivables > 0 ? "var(--negative)" : undefined }}>{money(e.overdue_receivables)}</td></tr>
                      <tr><td style={TD}>Payables</td><td style={{ ...TD, textAlign: "right" }}>{money(e.payables)}</td></tr>
                      <tr><td style={{ ...TD, fontWeight: 700 }}>Net</td><td style={{ ...TD, textAlign: "right", fontWeight: 700, color: e.net < 0 ? "var(--negative)" : "var(--positive)" }}>{money(e.net)}</td></tr>
                    </tbody>
                  </table>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
                    Ageing: current {money(e.ageing?.current)} · 1–30 {money(e.ageing?.["1_30"])} · 31–60 {money(e.ageing?.["31_60"])} · 61–90 {money(e.ageing?.["61_90"])} · 90+ {money(e.ageing?.["90_plus"])}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </PageSection>

      <PageSection title="Supplier performance" hint="From live purchase orders and receipts">
        {(f?.supplier || []).length === 0 ? (
          <Empty title="No supplier activity" good hint="No open purchase orders." />
        ) : (
          <Card>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr><th style={TH}>Supplier</th><th style={TH}>Open POs</th><th style={TH}>Late</th><th style={TH}>Received</th><th style={TH}>Fulfil %</th><th style={TH}>Verdict</th></tr></thead>
              <tbody>
                {(f?.supplier || []).map((s: any, i: number) => (
                  <tr key={i}>
                    <td style={TD}>{s.supplier}</td><td style={TD}>{num(s.open_pos)}</td>
                    <td style={{ ...TD, color: s.late_pos > 0 ? "var(--negative)" : undefined }}>{num(s.late_pos)}</td>
                    <td style={TD}>{num(s.received_pos)}</td><td style={TD}>{pct(s.fulfil_pct)}</td>
                    <td style={TD}><Verdict v={s.verdict} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </PageSection>

      <PageSection title="Delivery risk" hint="Open orders — projected against the promised date">
        {(f?.delivery || []).length === 0 ? (
          <Empty title="No open orders to project" good hint="Every order is delivered/billed, so there is nothing to forecast." />
        ) : (
          <Card>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr><th style={TH}>Order</th><th style={TH}>Style</th><th style={TH}>Ordered</th><th style={TH}>Packed</th><th style={TH}>Coverage</th><th style={TH}>Days left</th><th style={TH}>Miss prob.</th><th style={TH}>Verdict</th></tr></thead>
              <tbody>
                {(f?.delivery || []).map((d: any, i: number) => (
                  <tr key={i}>
                    <td style={TD}>{d.order}</td><td style={TD}>{d.style}</td><td style={TD}>{num(d.qty)}</td>
                    <td style={TD}>{num(d.packed)}</td><td style={TD}>{pct(d.coverage_pct)}</td><td style={TD}>{d.days_left ?? "—"}</td>
                    <td style={TD}>{Math.round((d.miss_probability || 0) * 100)}%</td><td style={TD}><Verdict v={d.verdict} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </PageSection>

      <PageSection title="Stock-out cover" hint="Fabric on hand vs required for open demand">
        {(f?.stockout || []).length === 0 ? (
          <Empty title="No open fabric demand" good hint="Fabric cover is projected only for open orders." />
        ) : (
          <Card>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr><th style={TH}>Style</th><th style={TH}>Required (m)</th><th style={TH}>Available (m)</th><th style={TH}>Cover</th><th style={TH}>Days cover</th><th style={TH}>Verdict</th></tr></thead>
              <tbody>
                {(f?.stockout || []).map((s: any, i: number) => (
                  <tr key={i}><td style={TD}>{s.style}</td><td style={TD}>{num(s.required_m)}</td><td style={TD}>{num(s.available_m)}</td>
                    <td style={TD}>{pct(s.cover_pct)}</td><td style={TD}>{s.days_cover ?? "—"}</td><td style={TD}><Verdict v={s.verdict} /></td></tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </PageSection>

      <PageSection title="Margin" hint={f?.margin_unverified ? `${f.margin_unverified} style(s) not verifiable — costing currency differs from order currency` : "Sell rate vs BOM material cost"}>
        {(f?.margin || []).length === 0 ? (
          <Empty title="Margin not verifiable from these records" hint={f?.note} />
        ) : (
          <Card>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr><th style={TH}>Style</th><th style={TH}>Sell rate</th><th style={TH}>Material cost</th><th style={TH}>Margin</th><th style={TH}>Verdict</th></tr></thead>
              <tbody>
                {(f?.margin || []).map((m: any, i: number) => (
                  <tr key={i}><td style={TD}>{m.style}</td><td style={TD}>{money(m.sell_rate)}</td><td style={TD}>{money(m.material_cost)}</td>
                    <td style={TD}>{pct(m.margin_pct)}</td><td style={TD}><Verdict v={m.verdict} /></td></tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </PageSection>

      {f?.note && (
        <div style={{ marginTop: 16, fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
          {f.note}
        </div>
      )}
    </>
  );
}
