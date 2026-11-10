import { AlertTriangle, ArrowRight, Building2, CheckCircle2, Database, Sparkles } from "lucide-react";
import type { Dashboard, Risk } from "../types";
import { fmtDate, fmtMonth, fmtTime, sevRank } from "../types";
import { Card, Empty, PageSection } from "../ui";
import { MetricTile } from "../components/MetricTile";
import { RiskRow } from "../components/RiskRow";
import type { CSSProperties } from "react";
import { BarChart, HGroupedBar } from "../charts";

const WIDE: CSSProperties = { gridColumn: "1 / -1" };

export function OverviewView(props: {
  dash: Dashboard;
  openRisks: Risk[];
  onOpenRisk: (r: Risk) => void;
  onGoRisks: () => void;
  onGoActions: () => void;
}) {
  const { dash, openRisks, onOpenRisk, onGoRisks, onGoActions } = props;

  const sorted = [...openRisks].sort((a, b) => sevRank(a.severity) - sevRank(b.severity));
  const attention = sorted.slice(0, 3);
  const critical = openRisks.filter((r) => r.severity === "critical").length;
  const orders = dash.buyer_orders || [];
  const nextDelivery = orders
    .map((o) => o.delivery_date)
    .filter(Boolean)
    .sort()[0];

  const pendingActions = dash.recommendations.filter((r) => r.approval_status === "pending").length;

  return (
    <div className="split">
      <div>
        {/* ── needs attention ─────────────────────────────────────────── */}
        <PageSection
          title="Needs attention"
          hint={`${critical} critical · ${openRisks.length - critical} warning — click any risk for the full evidence`}
          actions={
            <button className="btn btn--sm btn--ghost" onClick={onGoRisks}>
              All risks <ArrowRight size={13} />
            </button>
          }
        >
          <Card flush>
            {attention.length === 0 ? (
              <Empty good icon={<CheckCircle2 size={18} />} title="No open risks" hint="Every live signal is clear." />
            ) : (
              attention.map((r) => <RiskRow key={r.id} risk={r} onOpen={() => onOpenRisk(r)} />)
            )}
          </Card>
        </PageSection>

        {/* ── metrics ─────────────────────────────────────────────────── */}
        <PageSection title="Executive metrics" hint="Read live from KOGO ERP on every refresh">
          <div className="metrics">
            {dash.kpis.map((k) => <MetricTile key={k.key} kpi={k} />)}
          </div>
        </PageSection>

        {/* ── key charts ──────────────────────────────────────────────── */}
        <PageSection title="Operational pulse" actions={
          <button className="btn btn--sm btn--ghost" onClick={onGoActions}>All views <ArrowRight size={13} /></button>
        }>
          <div className="grid-charts">
            <Card title="Orders by delivery month" sub="Live sales orders (docstatus 1)">
              <BarChart
                data={(dash.charts.orders_at_risk || []).map((d: any) => ({ x: d.x, y: Number(d.y) || 0 }))}
                color="var(--chart-1)"
                format={(x) => fmtMonth(x)}
              />
            </Card>
            <Card style={WIDE} title="Ordered · factory packed · sent" sub="Ordered = live Sales Orders (PO qty) · Factory packed = production tracker (unverified) · Sent = final packing list / commercial invoice (authoritative)">
              <HGroupedBar
                data={[...(dash.charts.prod_plan_actual || [])].sort(
                  (a: any, b: any) =>
                    Math.abs((Number(b.sent) || 0) - (Number(b.planned) || 0)) -
                    Math.abs((Number(a.sent) || 0) - (Number(a.planned) || 0))
                )}
                series={[
                  { key: "planned", label: "Ordered (PO / SO)", color: "var(--chart-1)" },
                  { key: "actual", label: "Factory packed (unverified)", color: "var(--chart-3)" },
                  { key: "sent", label: "Sent — final packing list / invoice", color: "var(--chart-2)" },
                ]}
                rowLabel={(d) => String(d.x)}
                valueFmt={(v) => `${Math.round(v).toLocaleString()} pcs`}
              />
            </Card>
          </div>
        </PageSection>
      </div>

      {/* ── right rail ─────────────────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Card title="Live data source" sub="Live read + draft writes">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <Database size={14} style={{ color: "var(--text-muted)", marginTop: 2 }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{dash.source || "KOGO ERP"}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", wordBreak: "break-all" }}>
                  {dash.connection?.base || "base resolved at runtime"}
                </div>
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-secondary)" }}>
              <span>Last refresh</span><b>{fmtTime(dash.generated_at || "") || "—"}</b>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-secondary)" }}>
              <span>Mode</span><b>{dash.write_mode === "off" ? "Read-only" : `Read + ${dash.write_mode || "draft"} writes`}</b>
            </div>
            <div className="badge badge--positive" style={{ alignSelf: "flex-start" }}>
              <span className="badge__dot" />{dash.connection?.connected === false ? "Connection issue" : "Connected"}
            </div>
          </div>
        </Card>

        <Card title="Order book" sub="Live sales orders" actions={
          <button className="btn btn--sm btn--ghost" onClick={onGoActions} title="Open actions">View</button>
        }>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Stat label="Orders" value={orders.length.toLocaleString()} />
            <Stat label="Buyer" value={(orders[0]?.buyer_name as string) || "—"} small />
            <Stat label="Company" value={(orders[0]?.company as string) || "—"} small />
            <Stat label="Next delivery" value={fmtDate(nextDelivery)} />
            <Stat label="Open recommendations" value={String(pendingActions)} />
          </div>
        </Card>

        {/* ── ERP coverage: what the ERP actually holds, stage by stage ── */}
        {dash.erp_model && (dash.erp_model.stages || []).length > 0 && (
          <Card
            title="ERP coverage"
            sub="Live census of the process objects"
            actions={
              <span className={`badge badge--${(dash.erp_model.totals?.empty ?? 0) > 0 ? "warning" : "positive"}`}>
                <span className="badge__dot" />
                {dash.erp_model.totals?.populated ?? 0}/{dash.erp_model.totals?.objects ?? 0} populated
              </span>
            }
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {dash.erp_model.stages.map((st) => {
                const empty = st.objects.filter((o) => o.status !== "populated");
                return (
                  <div key={st.key}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12 }}>
                      <span style={{ color: "var(--text-secondary)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {st.label}
                      </span>
                      <b style={{ color: empty.length ? "var(--warning-ink)" : "var(--positive-ink)" }}>
                        {st.populated}/{st.total}
                      </b>
                    </div>
                    <div
                      title={empty.map((o) => `${o.doctype} (0)`).join(" · ") || "every object holds rows"}
                      style={{ height: 4, borderRadius: 2, background: "var(--border)", marginTop: 3, overflow: "hidden" }}
                    >
                      <div style={{ height: "100%", width: `${(st.populated / Math.max(st.total, 1)) * 100}%`, background: empty.length ? "var(--warning)" : "var(--positive)" }} />
                    </div>
                  </div>
                );
              })}
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 9, marginTop: 2, fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
                {(dash.erp_model.totals?.rows ?? 0).toLocaleString()} rows across {dash.erp_model.totals?.objects ?? 0} objects.
                {(dash.erp_model.totals?.empty ?? 0) > 0 && (
                  <>
                    {" "}Built but still empty:{" "}
                    <b style={{ color: "var(--text-secondary)" }}>
                      {dash.erp_model.stages.flatMap((st) => st.objects || []).filter((o) => o.status === "empty").map((o) => o.doctype).join(" · ")}
                    </b>
                  </>
                )}
              </div>
            </div>
          </Card>
        )}

        {attention.some((r) => r.severity === "critical") && (
          <Card title="Escalation" sub="Highest-severity signal">
            <div style={{ display: "flex", gap: 9 }}>
              <AlertTriangle size={15} style={{ color: "var(--negative)", marginTop: 2, flex: "0 0 15px" }} />
              <div style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>
                {attention[0].title}
              </div>
            </div>
            <button className="btn btn--sm" style={{ marginTop: 12, width: "100%" }} onClick={() => onOpenRisk(attention[0])}>
              Open evidence
            </button>
          </Card>
        )}

        <Card title="Recent activity" sub="Dashboard audit trail" flush>
          {(dash.audit_log || []).slice(0, 5).map((a) => (
            <div key={a.id} className="tl-item">
              <span className="tl-dot" style={{ background: "var(--chart-5)" }} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{a.action_name}</div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{fmtTime(a.timestamp)}</div>
              </div>
            </div>
          ))}
          {(dash.audit_log || []).length === 0 && (
            <Empty icon={<Sparkles size={16} />} title="No activity yet" hint="Approve or preview an action to start the trail." />
          )}
        </Card>

        <Card title="Companies in scope" sub="From live sales orders">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(dash.factories || []).map((f) => (
              <div key={f} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, color: "var(--text-secondary)" }}>
                <Building2 size={13} style={{ color: "var(--text-muted)" }} />
                {f}
              </div>
            ))}
            {(dash.factories || []).length === 0 && <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>—</span>}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
      <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{label}</span>
      <b style={{ fontSize: small ? 12 : 14, textAlign: "right", wordBreak: "break-word" }}>{value}</b>
    </div>
  );
}
