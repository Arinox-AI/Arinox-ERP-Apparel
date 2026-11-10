import type { CSSProperties } from "react";
import type { Dashboard } from "../types";
import { fmtMonth } from "../types";
import { Card, Empty } from "../ui";
import { BarChart, Donut, HBar, HGroupedBar, OrderedVsActual } from "../charts";

const WIDE: CSSProperties = { gridColumn: "1 / -1" };

export function OperationsView({ dash }: { dash: Dashboard }) {
  const c = dash.charts || {};
  // only charts that returned data are shown (the empty ones are hidden)
  const has = (k: string) => Array.isArray((c as any)[k]) && (c as any)[k].length > 0;
  const hasAny = Object.values(c).some((v) => Array.isArray(v) && v.length > 0);

  if (!hasAny) {
    return (
      <Card>
        <Empty title="No operational data" hint="The ERP returned no rows for these aggregations." />
      </Card>
    );
  }

  return (
    <div className="grid-charts">
      {has("orders_at_risk") && <Card title="Orders by promised delivery month" sub="Live customer orders">
        <BarChart
          data={(c.orders_at_risk || []).map((d: any) => ({ x: String(d.x), y: Number(d.y) || 0 }))}
          color="var(--chart-1)"
          format={fmtMonth}
          height={196}
        />
      </Card>}

      {has("supplier_delivery") && <Card title="Sourcing pipeline by type" sub="Live record counts across the sourcing chain">
        <Donut data={(c.supplier_delivery || []).map((d: any) => ({ x: String(d.x), y: Number(d.y) || 0 }))} />
      </Card>}

      {has("material_readiness") && <Card style={WIDE} title="Sewing minutes per style" sub="Standard allowed minutes (SAM) recorded in each bill of materials">
        <HBar
          data={(c.material_readiness || []).map((d: any) => ({ x: String(d.x), y: Number(d.y) || 0 }))}
          color="var(--chart-5)"
          valueFmt={(v) => `${v.toFixed(1)} min`}
        />
      </Card>}

      {has("prod_plan_actual") && <Card style={WIDE} title="Ordered · factory packed · sent" sub="Ordered = live Sales Orders (PO qty) · Factory packed = production tracker (unverified) · Sent = final packing list / commercial invoice (authoritative)">
        <HGroupedBar
          data={[...(c.prod_plan_actual || [])].sort(
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
      </Card>}

      {has("shipment_readiness") && <Card style={WIDE} title="Ordered vs shipped" sub="Garment shipments — the pale band is ordered, the solid fill is shipped; sorted by biggest gap">
        <OrderedVsActual
          data={c.shipment_readiness || []}
          orderedLabel="Ordered"
          actualLabel="Shipped"
          color="var(--chart-6)"
          topN={15}
        />
      </Card>}

      {has("order_margin") && <Card style={WIDE} title="Cut &amp; make cost vs operation cost" sub="USD per piece, from the BOM operation tables">
        <HGroupedBar
          data={c.order_margin || []}
          series={[
            { key: "expected", label: "Expected cost", color: "var(--chart-2)" },
            { key: "current", label: "Current cost", color: "var(--chart-3)" },
          ]}
          rowLabel={(d) => String(d.x)}
          valueFmt={(v) => `$${v.toFixed(2)}`}
        />
      </Card>}

      {has("quality_trends") && <Card style={WIDE} title="Fabric test results" sub="Quality certificates — pass, fail, or not conclusively extracted">
        <HGroupedBar
          data={c.quality_trends || []}
          series={[
            { key: "pass", label: "Pass", color: "var(--chart-2)" },
            { key: "fail", label: "Fail", color: "var(--chart-4)" },
            { key: "not_extracted", label: "Not conclusively extracted", color: "var(--chart-3)" },
          ]}
          rowLabel={(d) => String(d.x)}
        />
      </Card>}
    </div>
  );
}
