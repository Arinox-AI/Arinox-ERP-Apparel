import { useMemo, useState } from "react";
import { LayoutGrid, List as ListIcon } from "lucide-react";
import HeaderStrip from "../components/HeaderStrip";
import StatusBand, { type Bucket } from "../components/StatusBand";
import PhaseGantt from "../components/PhaseGantt";
import MilestoneTable from "../components/MilestoneTable";
import { fmtDate, fmtPct, fmtWdays } from "../lib/format";
import type { HolidayCalendar, TnaCalendar, TnaMilestone } from "../types";

function matchesBucket(m: TnaMilestone, b: Bucket): boolean {
  if (!b) return true;
  const s = m.status;
  if (b === "late") return s === "Overdue" || s === "Completed late";
  if (b === "done") return s === "Completed" || s === "Completed late";
  if (b === "atrisk") return s === "At risk" || s === "Blocked" || s.startsWith("Waiting");
  if (b === "ontrack") return s === "In progress" || s === "Not started";
  return true;
}

function MoreMetrics({ k }: { k: TnaCalendar["kpis"] }) {
  const items: [string, string][] = [
    ["Completed", `${k.completed_count}`],
    ["On-time", fmtPct(k.on_time_pct)],
    ["Critical done", `${k.critical_completed_count}/${k.critical_total}`],
    ["Critical-path delay", fmtWdays(k.critical_path_delay_days)],
    ["Days to ship", k.days_to_ship > 0 ? `+${k.days_to_ship}` : `${k.days_to_ship}`],
    ["Projected ship", fmtDate(k.projected_ship_date)],
    ["Awaiting approval", `${k.waiting_approval_count}`],
    ["Awaiting material", `${k.waiting_material_count}`],
    ["ERP-linked", `${k.erp_linked_count}/${k.total_milestones}`],
    ["Manual milestones", `${k.manual_count}`],
    ["No reason given", `${k.un_attributed_lates}`],
    ["Alerts", `${k.alert_count ?? 0}`],
  ];
  return (
    <div className="more-metrics">
      {items.map(([label, value]) => (
        <div key={label} className="mm-item">
          <div className="mm-label">{label}</div>
          <div className="mm-value mono">{value}</div>
        </div>
      ))}
    </div>
  );
}

/**
 * PlanView — the default view and the hero. Answers: is this order on track,
 * what's the timeline, and what's late. Compact header → status band → swimlane
 * timeline (or list) → more metrics on demand.
 */
export default function PlanView({
  payload, calendar, categories, onSelect,
}: {
  payload: TnaCalendar;
  calendar: HolidayCalendar | null;
  categories: string[];
  onSelect: (code: string) => void;
}) {
  const [bucket, setBucket] = useState<Bucket>("");
  const [mode, setMode] = useState<"timeline" | "list">("timeline");
  const [more, setMore] = useState(false);

  const filter = useMemo(() => (m: TnaMilestone) => matchesBucket(m, bucket), [bucket]);

  return (
    <div className="stack">
      <HeaderStrip header={payload.header} />
      <StatusBand kpis={payload.kpis} active={bucket} onSelect={setBucket} />

      <section className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="plan-toolbar">
          <div>
            <div className="card-title">Production timeline</div>
            <div className="card-sub">
              Backward-scheduled from the ship date · {payload.milestones.length} milestones
              {bucket ? ` · filtered: ${bucket}` : " · grouped by phase"}
            </div>
          </div>
          <div className="seg">
            <button className={`seg-btn${mode === "timeline" ? " active" : ""}`} onClick={() => setMode("timeline")}>
              <LayoutGrid size={14} /> Timeline
            </button>
            <button className={`seg-btn${mode === "list" ? " active" : ""}`} onClick={() => setMode("list")}>
              <ListIcon size={14} /> List
            </button>
          </div>
        </div>

        {mode === "timeline" ? (
          <PhaseGantt
            milestones={payload.milestones}
            calendar={calendar}
            shipDate={payload.header.ship_date}
            asOf={payload.as_of}
            categories={categories}
            onSelect={onSelect}
            filter={filter}
          />
        ) : (
          <div style={{ padding: 16 }}>
            <MilestoneTable
              milestones={bucket ? payload.milestones.filter(filter) : payload.milestones}
              selectedCode={null}
              onSelect={onSelect}
            />
          </div>
        )}
      </section>

      <section className="card" style={{ padding: 0 }}>
        <button className="more-toggle" onClick={() => setMore((v) => !v)}>
          <span>{more ? "Hide" : "Show"} detailed metrics</span>
          <span className="muted">{payload.kpis.total_milestones} milestones · {payload.data_quality.length} data notes</span>
        </button>
        {more && (
          <div style={{ padding: "4px 20px 20px" }}>
            <MoreMetrics k={payload.kpis} />
          </div>
        )}
      </section>
    </div>
  );
}
