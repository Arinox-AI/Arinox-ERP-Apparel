import { dayFlags } from "../lib/workingDays";
import { fmtDate } from "../lib/format";
import { toneColor, statusTone } from "../lib/status";
import StatusPill from "./StatusPill";
import { eventKindLabel, type Evt } from "./MonthCalendar";
import type { HolidayCalendar, TnaMilestone } from "../types";

/**
 * DayDetailPanel — the right-hand panel of the calendar. Shows everything due on
 * the selected day, with a status pill per milestone and a click-through to the
 * milestone drawer. Also renders the month summary when no day is selected.
 */
export default function DayDetailPanel({
  day, events, milestones, calendar, asOf, monthSummary, onSelect, onClear,
}: {
  day: string | null;
  events: Evt[];
  milestones: TnaMilestone[];
  calendar: HolidayCalendar | null;
  asOf: string;
  monthSummary: { label: string; planned: number; actual: number; ship: number; total: number };
  onSelect: (code: string) => void;
  onClear: () => void;
}) {
  if (!day) {
    return (
      <aside className="cal-side">
        <div className="cal-side-head">
          <span className="eyebrow">{monthSummary.label}</span>
        </div>
        <div className="cal-summary">
          <div className="cal-summary-row"><span>Planned finishes</span><span className="mono">{monthSummary.planned}</span></div>
          <div className="cal-summary-row"><span>Actual finishes</span><span className="mono">{monthSummary.actual}</span></div>
          <div className="cal-summary-row"><span>Ship dates</span><span className="mono">{monthSummary.ship}</span></div>
          <div className="cal-summary-row total"><span>Total events</span><span className="mono">{monthSummary.total}</span></div>
        </div>
        <div className="cal-side-hint muted">Click any day to see the milestones due on it.</div>
      </aside>
    );
  }

  const f = dayFlags(calendar, day, asOf);
  const byCode = new Map(milestones.map((m) => [m.code, m]));
  const dayName = new Date(`${day}T00:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <aside className="cal-side">
      <div className="cal-side-head">
        <span className="eyebrow">Day detail</span>
        <button className="btn btn-ghost btn-sm" onClick={onClear}>Back to month</button>
      </div>
      <div className="cal-side-day">{dayName}</div>
      <div className="cal-side-flags">
        <span className={`mini-flag ${f.isWorking ? "ok" : "off"}`}>{f.isWorking ? "Working day" : "Non-working"}</span>
        {f.isHoliday && <span className="mini-flag hol">{f.holidayLabel || "Holiday"}</span>}
        {f.isToday && <span className="mini-flag today">Today</span>}
      </div>

      {events.length === 0 && <div className="cal-side-empty muted">Nothing due on this day.</div>}

      <div className="cal-day-list">
        {events.map((e) => {
          const m = byCode.get(e.code);
          return (
            <button key={e.kind + e.code} className="cal-day-item" onClick={() => onSelect(e.code)}
              style={{ borderLeftColor: e.kind === "ship" ? "var(--error)" : e.kind === "actual" ? "var(--success)" : toneColor(statusTone(e.status)) }}>
              <span className="cal-day-item-top">
                <span className="cal-day-item-name">{e.name}</span>
                <span className={`kind-chip kind-${e.kind}`}>{eventKindLabel(e.kind)}</span>
              </span>
              <span className="cal-day-item-meta">
                <span className="mono">{e.code}</span>
                {e.critical && <span className="cp-tag">◆ critical</span>}
              </span>
              {m && (
                <span className="cal-day-item-foot">
                  <StatusPill status={m.status} />
                  <span className="muted">{fmtDate(m.planned_finish)} → {fmtDate(m.actual_finish)}</span>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </aside>
  );
}
