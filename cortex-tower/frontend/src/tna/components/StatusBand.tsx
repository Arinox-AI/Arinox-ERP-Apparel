import { fmtPct } from "../lib/format";
import type { TnaKpi } from "../types";

/**
 * StatusBand — the 4 big RAG buckets a planner actually reads first.
 * "On track · At risk · Late · Done". Clicking a bucket filters the plan.
 * Replaces the 9-card KPI row of v1 (the extra 5 metrics live behind "more metrics").
 */
export type Bucket = "ontrack" | "atrisk" | "late" | "done" | "";

export interface BandModel {
  onTrack: number;
  atRisk: number;
  late: number;
  done: number;
  total: number;
  onTimePct: number;
  progress: number;
}

export function bandFromKpis(k: TnaKpi): BandModel {
  const done = k.completed_count ?? 0;
  const late = (k.overdue_count ?? 0) + (k.completed_late_count ?? 0);
  const atRisk = (k.at_risk_count ?? 0) + (k.blocked_count ?? 0)
    + (k.waiting_approval_count ?? 0) + (k.waiting_material_count ?? 0);
  const total = k.total_milestones ?? 0;
  const onTrack = Math.max(total - done - late - atRisk - (k.not_recorded_count ?? 0), 0);
  return {
    onTrack, atRisk, late, done, total,
    onTimePct: k.on_time_pct ?? 0,
    progress: k.progress_pct ?? 0,
  };
}

function Tile({
  label, value, tone, sub, active, onClick,
}: {
  label: string; value: number; tone: string; sub: string;
  active: boolean; onClick: () => void;
}) {
  return (
    <button
      className={`band-tile tone-${tone}${active ? " active" : ""}`}
      onClick={onClick}
      aria-pressed={active}
    >
      <span className="band-tile-dot" />
      <span className="band-tile-value">{value}</span>
      <span className="band-tile-label">{label}</span>
      <span className="band-tile-sub">{sub}</span>
    </button>
  );
}

export default function StatusBand({
  kpis, active, onSelect,
}: {
  kpis: TnaKpi;
  active: Bucket;
  onSelect: (b: Bucket) => void;
}) {
  const b = bandFromKpis(kpis);
  const pick = (x: Bucket) => onSelect(active === x ? "" : x);
  return (
    <section className="status-band" role="group" aria-label="Milestone status">
      <Tile label="Late" value={b.late} tone="red" active={active === "late"}
        sub="overdue + done late" onClick={() => pick("late")} />
      <Tile label="At risk" value={b.atRisk} tone="amber" active={active === "atrisk"}
        sub="at risk · blocked · awaiting" onClick={() => pick("atrisk")} />
      <Tile label="On track" value={b.onTrack} tone="teal" active={active === "ontrack"}
        sub="not yet due" onClick={() => pick("ontrack")} />
      <Tile label="Done" value={b.done} tone="navy" active={active === "done"}
        sub={`${fmtPct(b.onTimePct)} on time`} onClick={() => pick("done")} />
      <div className="band-progress" title="Duration-weighted build completion">
        <div className="band-progress-label">
          <span>Build progress</span><span className="mono">{b.progress}%</span>
        </div>
        <div className="band-progress-track">
          <div className="band-progress-fill" style={{ width: `${Math.min(b.progress, 100)}%` }} />
        </div>
        <div className="band-progress-sub muted">{b.done} of {b.total} milestones complete</div>
      </div>
    </section>
  );
}
