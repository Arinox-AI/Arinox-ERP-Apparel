import { useEffect, useState } from "react";
import KpiCard from "./KpiCard";
import { fmtDate, fmtPct, fmtWdays } from "../lib/format";
import { getTnaKpis, unwrap } from "../services/tna";
import type { TnaKpi, TnaKpisResponse } from "../types";

/**
 * KPI row — on-time %, overdue, at-risk, blocked, critical-path delay, days to
 * ship, projected ship (SPEC §13.1). KpiRow is the component designated to call
 * `get_tna_kpis`; the calendar payload's KPI block is used as the initial value
 * so the row renders instantly and never goes blank. The client only maps the
 * backend values to tones — it never re-derives them.
 */
export default function KpiRow({
  kpis, orderId, calendar, asOf,
}: {
  kpis: TnaKpi;
  orderId: string;
  calendar: string;
  asOf: string;
}) {
  const [live, setLive] = useState<TnaKpi | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getTnaKpis({ order_id: orderId, calendar, as_of: asOf });
        const u = unwrap<TnaKpisResponse>(res);
        if (alive && u.data?.kpis) setLive(u.data.kpis);
      } catch { /* keep the initial payload KPIs */ }
    })();
    return () => { alive = false; };
  }, [orderId, calendar, asOf, kpis]);

  const k = live ?? kpis;
  const onTimeTone = k.on_time_pct >= 100 ? "green" : k.on_time_pct >= 90 ? "amber" : "red";
  const slipTone = k.projected_slip_days > 0 ? "red" : "green";
  const dtsTone = k.days_to_ship < 0 ? "red" : k.days_to_ship <= 7 ? "amber" : "navy";

  return (
    <section className="kpi-row">
      <KpiCard
        label="On-time milestones"
        value={fmtPct(k.on_time_pct)}
        tone={onTimeTone as any}
        sub={`${k.completed_on_time_count}/${k.completed_count} completed · ${k.completed_late_count} late`}
      />
      <KpiCard
        label="Overdue"
        value={k.overdue_count}
        tone={k.overdue_count > 0 ? "red" : "green"}
        sub={`${k.un_attributed_lates} without a reason`}
      />
      <KpiCard
        label="At risk"
        value={k.at_risk_count}
        tone={k.at_risk_count > 0 ? "amber" : "green"}
        sub={`${k.waiting_approval_count} awaiting approval`}
      />
      <KpiCard
        label="Blocked"
        value={k.blocked_count}
        tone={k.blocked_count > 0 ? "red" : "green"}
        sub={`${k.waiting_material_count} waiting material`}
      />
      <KpiCard
        label="Critical-path delay"
        value={fmtWdays(k.critical_path_delay_days)}
        small
        tone={k.critical_path_delay_days > 0 ? "red" : "green"}
        sub={`${k.critical_completed_count}/${k.critical_total} critical done`}
      />
      <KpiCard
        label="Days to ship"
        value={k.days_to_ship > 0 ? `+${k.days_to_ship}` : k.days_to_ship}
        tone={dtsTone as any}
        sub={k.ship_overdue_days > 0 ? `${k.ship_overdue_days} wd past ship` : "vs required ship date"}
      />
      <KpiCard
        label="Projected ship"
        value={<span style={{ fontSize: 17 }}>{fmtDate(k.projected_ship_date)}</span>}
        tone={slipTone as any}
        sub={`${k.on_time_vs_required}${k.projected_slip_days > 0 ? ` · +${k.projected_slip_days} wd slip` : ""}`}
      />
      <KpiCard
        label="Plan progress"
        value={`${k.progress_pct ?? 0}%`}
        tone={(k.progress_pct ?? 0) >= 99 ? "green" : "amber"}
        sub="duration-weighted completion"
      />
      <KpiCard
        label="ERP-linked"
        value={`${k.erp_linked_count ?? 0}/${k.total_milestones ?? 0}`}
        tone={k.erp_linked_count ? "teal" : "navy"}
        sub={`${k.manual_count ?? 0} manual milestones`}
      />
    </section>
  );
}
