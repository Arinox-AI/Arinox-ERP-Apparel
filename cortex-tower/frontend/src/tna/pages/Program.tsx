import { useEffect, useMemo, useState } from "react";
import KpiCard from "../components/KpiCard";
import ProgramTable from "../components/ProgramTable";
import { getTnaProgram, unwrap } from "../services/tna";
import { fmtInt } from "../lib/format";
import type { ProgramResponse } from "../types";

/**
 * Multi-order / capacity view. Reads `get_tna_program` with `detail=true` so the
 * per-order KPIs are the live (ERP-linked) ones. The sweep reads every order's
 * milestones, so on a large portfolio this call can take a few seconds.
 */
export default function Program({
  asOf, calendar, onOpen,
}: {
  asOf: string;
  calendar: string;
  onOpen: (orderId: string) => void;
}) {
  const [data, setData] = useState<ProgramResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issuesOnly, setIssuesOnly] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const res = await getTnaProgram({ as_of: asOf, calendar, detail: true });
        const u = unwrap<ProgramResponse>(res);
        if (!alive) return;
        if (u.error || !u.data) setError(u.error || "Failed to load the program view");
        else { setError(null); setData(u.data); }
      } catch (e: any) {
        if (alive) setError(e?.message || "Request failed");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [asOf, calendar]);

  const months = data?.capacity_by_ship_month ?? [];
  const maxQty = Math.max(1, ...months.map((m) => m.qty));
  const orders = useMemo(
    () => (data?.orders ?? []).filter((o) => !issuesOnly || (o.overdue_count || 0) > 0 || o.rag === "red"),
    [data, issuesOnly]
  );

  if (loading && !data) {
    return (
      <div className="stack">
        <div className="card-head">
          <div className="card-title">Program / capacity</div>
          <div className="card-sub">Reading every order's TnA from the ERP — this can take a few seconds.</div>
        </div>
        <div className="loading-wrap"><span className="spinner" /> Building the multi-order view…</div>
      </div>
    );
  }
  if (error && !data) {
    return <div className="empty"><div className="empty-title">Could not load the program view</div><div>{error}</div></div>;
  }
  if (!data) return null;

  return (
    <div className="stack">
      <section className="kpi-row">
        <KpiCard label="Orders" value={data.total_orders} tone="navy" sub={`${fmtInt(data.qty_total)} pcs total`} />
        <KpiCard label="Ship date passed" value={data.orders_ship_past} tone={data.orders_ship_past ? "red" : "green"}
          sub="past the required ship date" />
        <KpiCard label={`Shipping ≤ ${data.horizon_wd} wd`} value={data.orders_ship_within_horizon} tone="amber"
          sub="inside the horizon window" />
        <KpiCard label="Red / Amber / Green" value={`${data.by_rag.red} / ${data.by_rag.amber} / ${data.by_rag.green}`}
          tone={data.by_rag.red ? "red" : "green"} sub="order-level RAG" />
        <KpiCard label="Ship months loaded" value={months.length} tone="teal" sub="months with a ship date" />
        <KpiCard label="Source" value={data.source} tone="navy" sub={data.detail ? "live per-order KPIs" : "plan-based"} />
      </section>

      <section className="card" style={{ padding: 16 }}>
        <div className="card-head" style={{ marginBottom: 10 }}>
          <div>
            <div className="card-title">Capacity by ship month</div>
            <div className="card-sub">Order count and quantity loading per month — the same month shipping together is capacity pressure.</div>
          </div>
        </div>
        <div className="stack-sm">
          {months.map((m) => {
            const pct = Math.round((m.qty / maxQty) * 100);
            const critical = m.red > 0;
            return (
              <div key={m.month} className="row" style={{ gap: 10, alignItems: "center" }}>
                <span className="mono" style={{ width: 76, fontSize: 12 }}>{m.month}</span>
                <span style={{ flex: 1, height: 16, background: "var(--surface-accent)", borderRadius: 3, overflow: "hidden", display: "block" }}>
                  <span style={{
                    display: "block", height: "100%", width: `${pct}%`,
                    background: critical ? "var(--error)" : "var(--accent-teal)",
                    opacity: 0.85,
                  }} />
                </span>
                <span className="mono muted" style={{ width: 150, fontSize: 11, textAlign: "right" }}>
                  {m.orders} order{m.orders === 1 ? "" : "s"} · {fmtInt(m.qty)} pcs · {m.overdue} overdue
                </span>
              </div>
            );
          })}
          {months.length === 0 && <div className="muted">No ship dates available.</div>}
        </div>
      </section>

      <div className="card-head">
        <div>
          <div className="card-title">Orders ({orders.length})</div>
          <div className="card-sub">Click a row to open that order's full TnA calendar.</div>
        </div>
        <button className={`chip clickable${issuesOnly ? " on" : ""}`} onClick={() => setIssuesOnly(!issuesOnly)}
          title="Show only orders with overdue milestones">
          ⚠ Issues only
        </button>
      </div>
      <ProgramTable orders={orders} onOpen={onOpen} />

      {loading && <div className="muted mono" style={{ fontSize: 12 }}>Refreshing…</div>}
    </div>
  );
}
