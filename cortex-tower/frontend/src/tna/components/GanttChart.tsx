import { useMemo } from "react";
import { dayFlags, daysBetween } from "../lib/workingDays";
import { fmtDate, fmtWdays, parseISO } from "../lib/format";
import type { HolidayCalendar, TnaMilestone } from "../types";

const DAY_MS = 86400000;

function diffDays(aISO: string, bISO: string): number {
  const a = parseISO(aISO), b = parseISO(bISO);
  if (!a || !b) return 0;
  return Math.round((b.getTime() - a.getTime()) / DAY_MS);
}

interface Axis {
  min: string;
  max: string;
  days: string[];
  n: number;
  x: (iso: string) => number; // 0..100
}

export type { Axis };

export function buildAxis(milestones: TnaMilestone[], shipDate: string | null, asOf: string): Axis & { todayPinned: boolean; todayLeftPinned: boolean } {
  const dates: string[] = [];
  const push = (d: string | null | undefined) => { if (d) dates.push(d); };
  milestones.forEach((m) => { push(m.planned_start); push(m.planned_finish); push(m.actual_start); push(m.actual_finish); });
  push(shipDate);
  push(asOf);
  dates.sort();
  let min = dates[0];
  let max = dates[dates.length - 1];

  // Keep the axis readable: if "today" is far outside the plan window, do not let
  // it stretch the axis; instead pin a marker to the nearest edge.
  let todayPinned = false, todayLeftPinned = false;
  const planDates = milestones.flatMap((m) => [m.planned_start, m.planned_finish].filter(Boolean) as string[]);
  if (planDates.length) {
    planDates.sort();
    const pMin = planDates[0], pMax = planDates[planDates.length - 1];
    if (asOf > pMax) {
      if (diffDays(pMax, asOf) <= 45) max = asOf > max ? asOf : max;
      else { max = pMax; todayPinned = true; }
      min = min < pMin ? min : pMin;
    } else if (asOf < pMin) {
      if (diffDays(asOf, pMin) <= 45) min = asOf < min ? asOf : min;
      else { min = pMin; todayLeftPinned = true; }
      max = max > pMax ? max : pMax;
    }
  }

  const days = daysBetween(min, max);
  const n = Math.max(days.length, 1);
  const x = (iso: string) => {
    const d = diffDays(min, iso);
    return Math.max(0, Math.min(100, (d / n) * 100));
  };
  return { min, max, days, n, x, todayPinned, todayLeftPinned };
}

export function monthSegments(days: string[]): { label: string; widthPct: number }[] {
  const segs: { label: string; widthPct: number }[] = [];
  let cur = "";
  let count = 0;
  days.forEach((iso) => {
    const d = parseISO(iso)!;
    const label = d.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
    if (label !== cur) {
      if (cur) segs.push({ label: cur, widthPct: (count / days.length) * 100 });
      cur = label; count = 1;
    } else count++;
  });
  if (cur) segs.push({ label: cur, widthPct: (count / days.length) * 100 });
  return segs;
}

export function GanttRow({
  m, axis, cal, shipDate, asOf, onSelect,
}: {
  m: TnaMilestone;
  axis: Axis;
  cal: HolidayCalendar | null;
  shipDate: string | null;
  asOf: string;
  onSelect: (code: string) => void;
}) {
  const dayPct = 100 / axis.n;
  const miniW = Math.max(dayPct, 0.9);

  const plannedBar = m.planned_start && m.planned_finish
    ? { left: axis.x(m.planned_start), width: Math.max(axis.x(m.planned_finish) - axis.x(m.planned_start) + dayPct, miniW) }
    : null;

  const aStart = m.actual_start || m.actual_finish;
  const aFinish = m.actual_finish || m.actual_start;
  const actualBar = aStart && aFinish
    ? { left: axis.x(aStart), width: Math.max(axis.x(aFinish) - axis.x(aStart) + dayPct, miniW) }
    : null;

  const forecastX = (m.forecast_finish && m.forecast_finish !== m.actual_finish && m.forecast_finish !== m.planned_finish)
    ? axis.x(m.forecast_finish)
    : null;

  const title = [
    `${m.seq}. ${m.code} — ${m.name}`,
    `Status: ${m.status}${m.is_critical ? " · on critical path" : ""}`,
    `Planned: ${fmtDate(m.planned_start)} → ${fmtDate(m.planned_finish)}`,
    `Actual:  ${fmtDate(m.actual_start)} → ${fmtDate(m.actual_finish)}`,
    `Forecast: ${fmtDate(m.forecast_finish)}`,
    `Delay:   ${fmtWdays(m.delay_days)}   Float: ${m.float_days === null || m.float_days === undefined ? "—" : m.float_days + " wd"}`,
    `Progress: ${Math.round(m.progress_pct ?? 0)}%   Owner: ${m.owner}`,
  ].join("\n");

  return (
    <div
      className={`gantt-row${m.is_critical ? " gantt-critical" : ""}`}
      onClick={() => onSelect(m.code)}
      title={title}
    >
      <div className="gantt-label-col row-label">
        <span className="gantt-code mono" title={m.code}>{m.code}</span>
        {m.is_critical && <span className="gantt-cp-flag" title="On the critical path">◆</span>}
        <span className="gantt-name">{m.name}</span>
      </div>
      <div className="gantt-row-track">
        {plannedBar && (
          <div
            className={`gantt-bar planned${m.is_critical ? " critical" : ""}`}
            style={{ left: `${plannedBar.left}%`, width: `${plannedBar.width}%` }}
          />
        )}
        {actualBar && (
          <div
            className="gantt-bar actual"
            style={{ left: `${actualBar.left}%`, width: `${actualBar.width}%` }}
          />
        )}
        {forecastX !== null && (
          <div
            title={`Forecast finish ${fmtDate(m.forecast_finish)}`}
            style={{
              position: "absolute", left: `${forecastX}%`, top: "50%",
              transform: "translate(-50%, -50%) rotate(45deg)",
              width: 7, height: 7, background: "var(--warning)",
              border: "1px solid #fff", zIndex: 3,
            }}
          />
        )}
      </div>
    </div>
  );
}

export default function GanttChart({
  milestones, calendar, shipDate, asOf, onSelect,
}: {
  milestones: TnaMilestone[];
  calendar: HolidayCalendar | null;
  shipDate: string | null;
  asOf: string;
  onSelect: (code: string) => void;
}) {
  const axis = useMemo(() => buildAxis(milestones, shipDate, asOf), [milestones, shipDate, asOf]);
  const months = useMemo(() => monthSegments(axis.days), [axis.days]);

  const holidayBands = useMemo(() => {
    return axis.days
      .map((iso, i) => ({ iso, i, flags: dayFlags(calendar, iso, asOf) }))
      .filter((d) => d.flags.isHoliday || d.flags.isWeekend);
  }, [axis.days, calendar, asOf]);

  const shipX = shipDate ? axis.x(shipDate) : null;
  const todayInRange = asOf >= axis.min && asOf <= axis.max;

  return (
    <section className="gantt">
      <div className="gantt-scroll">
        <div className="gantt-grid">
          <div className="gantt-head">
            <div className="gantt-label-col">
              <div style={{ height: 36 }} />
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
                <div
                  key={b.iso}
                  className="gantt-band"
                  style={{ left: `${(b.i / axis.n) * 100}%`, width: `${(1 / axis.n) * 100}%` }}
                />
              ))}
              {shipX !== null && (
                <div className="gantt-ship" style={{ left: `${shipX}%` }} title={`Ship date ${fmtDate(shipDate)} (anchor)`} />
              )}
              {todayInRange && (
                <div className="gantt-today" style={{ left: `${axis.x(asOf)}%` }} title={`Today / as-of ${fmtDate(asOf)}`} />
              )}
              {axis.todayPinned && (
                <div className="gantt-today-pin" title={`Today / as-of ${fmtDate(asOf)} is past this order window`}>
                  today ▸
                </div>
              )}
              {axis.todayLeftPinned && (
                <div className="gantt-today-pin left" title={`Today / as-of ${fmtDate(asOf)} is before this order window`}>
                  ◂ today
                </div>
              )}
            </div>

            {milestones.map((m) => (
              <GanttRow key={m.code} m={m} axis={axis} cal={calendar} shipDate={shipDate} asOf={asOf} onSelect={onSelect} />
            ))}
          </div>
        </div>
      </div>

      <div className="gantt-legend">
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--primary)" }} /> Planned (critical path)</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--accent-teal)" }} /> Planned (non-critical)</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--text-muted)" }} /> Actual <span style={{ marginLeft: 2, color: "var(--success)" }}>▍</span></span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--warning)", transform: "rotate(45deg)", width: 8, height: 8 }} /> Forecast</span>
        <span className="legend-item"><span className="legend-line" style={{ background: "var(--primary)" }} /> Today</span>
        <span className="legend-item"><span className="legend-line" style={{ background: "var(--error)" }} /> Ship date</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "rgba(254,243,199,0.9)", borderLeft: "1px solid var(--warning)" }} /> Holiday</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--surface)", border: "1px solid var(--border)" }} /> Non-working</span>
        <span className="legend-item muted mono">{fmtDate(axis.min)} → {fmtDate(axis.max)} · {axis.n} days</span>
      </div>
    </section>
  );
}
