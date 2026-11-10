import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { dayFlags, daysBetween } from "../lib/workingDays";
import { fmtDate } from "../lib/format";
import { statusTone, toneColor } from "../lib/status";
import { buildAxis, monthSegments, GanttRow } from "./GanttChart";
import StatusPill from "./StatusPill";
import type { HolidayCalendar, TnaMilestone } from "../types";

/**
 * PhaseGantt — the plan's hero: one swimlane per phase (category), collapsible,
 * with a mini progress bar per phase. Rows are the same milestones as the flat
 * Gantt but grouped, so a planner reads the schedule phase by phase.
 */
export default function PhaseGantt({
  milestones, calendar, shipDate, asOf, categories, onSelect, filter,
}: {
  milestones: TnaMilestone[];
  calendar: HolidayCalendar | null;
  shipDate: string | null;
  asOf: string;
  categories: string[];
  onSelect: (code: string) => void;
  filter?: (m: TnaMilestone) => boolean;
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const shown = useMemo(
    () => (filter ? milestones.filter(filter) : milestones),
    [milestones, filter]
  );

  const axis = useMemo(() => buildAxis(shown.length ? shown : milestones, shipDate, asOf), [shown, milestones, shipDate, asOf]);
  const months = useMemo(() => monthSegments(axis.days), [axis.days]);

  const groups = useMemo(() => {
    const order = categories.length ? categories : Array.from(new Set(shown.map((m) => m.category)));
    return order
      .map((cat) => ({ cat, rows: shown.filter((m) => m.category === cat) }))
      .filter((g) => g.rows.length > 0);
  }, [shown, categories]);

  const holidayBands = useMemo(
    () => axis.days.map((iso, i) => ({ iso, i, flags: dayFlags(calendar, iso, asOf) }))
      .filter((d) => d.flags.isHoliday || d.flags.isWeekend),
    [axis.days, calendar, asOf]
  );

  const shipX = shipDate ? axis.x(shipDate) : null;
  const todayInRange = asOf >= axis.min && asOf <= axis.max;

  return (
    <section className="gantt">
      <div className="gantt-scroll">
        <div className="gantt-grid">
          <div className="gantt-head">
            <div className="gantt-label-col">
              <div className="gantt-head-h">Phase / milestone</div>
            </div>
            <div className="gantt-track-col">
              <div className="gantt-month-row">
                {months.map((s, i) => (
                  <div key={i} className="gantt-month" style={{ width: `${s.widthPct}%` }}>{s.label}</div>
                ))}
              </div>
              <div className="gantt-day-row">
                {holidayBands.map((b) => (
                  <div
                    key={b.iso}
                    className={b.flags.isHoliday ? "gantt-holiday-shade" : "gantt-nonwork-shade"}
                    style={{ left: `${(b.i / axis.n) * 100}%`, width: `${(1 / axis.n) * 100}%` }}
                    title={b.flags.isHoliday ? `Holiday: ${b.flags.holidayLabel}` : "Non-working day"}
                  />
                ))}
              </div>
            </div>
          </div>

          <div className="gantt-body" style={{ position: "relative" }}>
            <div className="gantt-overlay">
              {holidayBands.filter((b) => b.flags.isHoliday).map((b) => (
                <div key={b.iso} className="gantt-band"
                  style={{ left: `${(b.i / axis.n) * 100}%`, width: `${(1 / axis.n) * 100}%` }} />
              ))}
              {shipX !== null && (
                <div className="gantt-ship" style={{ left: `${shipX}%` }}
                  title={`Ship date ${fmtDate(shipDate)} (anchor)`} />
              )}
              {todayInRange && (
                <div className="gantt-today" style={{ left: `${axis.x(asOf)}%` }}
                  title={`Today / as-of ${fmtDate(asOf)}`} />
              )}
            </div>

            {groups.map(({ cat, rows }) => {
              const isCollapsed = !!collapsed[cat];
              const done = rows.filter((r) => r.status === "Completed" || r.status === "Completed late").length;
              const late = rows.filter((r) => r.status === "Overdue" || r.status === "Completed late").length;
              const pct = rows.length ? Math.round((done / rows.length) * 100) : 0;
              return (
                <div key={cat} className="gantt-phase">
                  <button
                    className="gantt-phase-head"
                    onClick={() => setCollapsed((c) => ({ ...c, [cat]: !c[cat] }))}
                  >
                    {isCollapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
                    <span className="gantt-phase-name">{cat}</span>
                    <span className="gantt-phase-meta muted">
                      {done}/{rows.length} done{late ? ` · ${late} late` : ""}
                    </span>
                    <span className="gantt-phase-bar">
                      <span className="gantt-phase-bar-fill" style={{ width: `${pct}%` }} />
                    </span>
                    <span className="gantt-phase-pct mono">{pct}%</span>
                  </button>
                  {!isCollapsed && rows.map((m) => (
                    <GanttRow key={m.code} m={m} axis={axis} cal={calendar} shipDate={shipDate} asOf={asOf} onSelect={onSelect} />
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="gantt-legend">
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--primary)" }} /> Planned (critical path)</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--accent-teal)" }} /> Planned (non-critical)</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--text-muted)" }} /> Actual</span>
        <span className="legend-item"><span className="legend-line" style={{ background: "var(--primary)" }} /> Today</span>
        <span className="legend-item"><span className="legend-line" style={{ background: "var(--error)" }} /> Ship date</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "rgba(254,243,199,0.9)", borderLeft: "1px solid var(--warning)" }} /> Holiday</span>
        <span className="legend-item muted mono">{fmtDate(axis.min)} → {fmtDate(axis.max)}</span>
      </div>
    </section>
  );
}

/** Small helper reused by the rail/board to colour a milestone's left border. */
export function milestoneTone(m: TnaMilestone) {
  return toneColor(statusTone(m.status));
}
