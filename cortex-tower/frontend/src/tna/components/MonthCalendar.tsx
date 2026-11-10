import { useMemo } from "react";
import { dayFlags } from "../lib/workingDays";
import { fmtDate, monthLabel, toISO, parseISO } from "../lib/format";
import { statusTone, toneColor } from "../lib/status";
import type { HolidayCalendar, TnaMilestone } from "../types";

export interface MonthRef { y: number; m0: number; }

export interface Evt {
  code: string;
  name: string;
  kind: "planned" | "actual" | "ship";
  status: string;
  critical: boolean;
}

/** Build the day → events map once for the whole order window. */
export function buildEventMap(milestones: TnaMilestone[], shipDate: string | null) {
  const map = new Map<string, Evt[]>();
  const add = (iso: string | null, e: Evt) => {
    if (!iso) return;
    const arr = map.get(iso) || [];
    if (!arr.some((x) => x.code === e.code && x.kind === e.kind)) arr.push(e);
    map.set(iso, arr);
  };
  milestones.forEach((m) => {
    const base = { code: m.code, name: m.name, status: m.status, critical: !!m.is_critical };
    add(m.planned_finish, { ...base, kind: "planned" });
    if (m.actual_finish) add(m.actual_finish, { ...base, kind: "actual" });
  });
  if (shipDate) add(shipDate, {
    code: "SHIP", name: "Ship date (anchor)", kind: "ship", status: "Overdue", critical: true,
  });
  return map;
}

function monthDays(y: number, m0: number): (string | null)[] {
  const first = new Date(y, m0, 1);
  const daysInMonth = new Date(y, m0 + 1, 0).getDate();
  const lead = (first.getDay() + 6) % 7; // Mon-first
  const cells: (string | null)[] = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(toISO(new Date(y, m0, d)));
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function eventKindLabel(kind: Evt["kind"]): string {
  return kind === "actual" ? "Actual" : kind === "ship" ? "Ship" : "Planned";
}

/** One large month — the primary calendar view. Cells are roomy and events readable. */
export function MonthGrid({
  y, m0, calendar, asOf, events, onSelect, selectedDay, onSelectDay,
}: {
  y: number;
  m0: number;
  calendar: HolidayCalendar | null;
  asOf: string;
  events: Map<string, Evt[]>;
  onSelect: (code: string) => void;
  selectedDay: string | null;
  onSelectDay: (iso: string) => void;
}) {
  const cells = useMemo(() => monthDays(y, m0), [y, m0]);

  return (
    <div className="cal-grid cal-grid-lg">
      {DOW.map((d) => <div key={d} className="cal-dow">{d}</div>)}
      {cells.map((iso, i) => {
        if (!iso) return <div key={i} className="cal-cell cal-cell-lg empty" />;
        const f = dayFlags(calendar, iso, asOf);
        const evts = events.get(iso) || [];
        const shown = evts.slice(0, 4);
        const cls = ["cal-cell", "cal-cell-lg"];
        if (f.isHoliday) cls.push("holiday");
        else if (!f.isWorking) cls.push("nonwork");
        if (f.isToday) cls.push("today");
        if (iso === selectedDay) cls.push("selected");
        const dnum = parseISO(iso)!.getDate();
        return (
          <div
            key={i}
            className={cls.join(" ")}
            onClick={() => onSelectDay(iso)}
            title={f.isHoliday ? `Holiday: ${f.holidayLabel}` : undefined}
          >
            <div className="cal-day-lg">
              <span className={`cal-daynum${f.isToday ? " today" : ""}`}>{dnum}</span>
              {f.isHoliday && f.holidayLabel && <span className="cal-hol-chip">{f.holidayLabel}</span>}
            </div>
            <div className="cal-evts">
              {shown.map((e) => (
                <button
                  key={e.kind + e.code}
                  className={`cal-evt cal-evt-lg kind-${e.kind}`}
                  onClick={(ev) => { ev.stopPropagation(); onSelect(e.code); }}
                  title={`${eventKindLabel(e.kind)} · ${e.name} · ${e.status} · ${fmtDate(iso)}`}
                  style={{ borderLeftColor: e.kind === "ship" ? "var(--error)" : e.kind === "actual" ? "var(--success)" : toneColor(statusTone(e.status)) }}
                >
                  <span className="cal-evt-dot" style={{ background: e.kind === "ship" ? "var(--error)" : e.kind === "actual" ? "var(--success)" : toneColor(statusTone(e.status)) }} />
                  <span className="cal-evt-code mono">{e.code}</span>
                  <span className="cal-evt-name">{e.name}</span>
                </button>
              ))}
              {evts.length > 4 && <div className="cal-more-lg">+{evts.length - 4} more</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function CalendarLegend({ cal }: { cal: HolidayCalendar | null }) {
  return (
    <div className="gantt-legend cal-legend">
      <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--surface-accent)", borderLeft: "2px solid var(--primary)" }} /> Planned finish</span>
      <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--success-light)", borderLeft: "2px solid var(--success)" }} /> Actual finish</span>
      <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--error-light)", borderLeft: "2px solid var(--error)" }} /> Ship date</span>
      <span className="legend-item"><span className="legend-swatch" style={{ background: "rgba(254,243,199,0.9)", borderLeft: "1px solid var(--warning)" }} /> Holiday</span>
      <span className="legend-item"><span className="legend-swatch" style={{ background: "var(--surface)", border: "1px solid var(--border)" }} /> Non-working</span>
      {cal && <span className="legend-item muted">{cal.label} · {cal.working_week_label}</span>}
      {cal && cal.special_working_days.length > 0 && (
        <span className="legend-item" style={{ color: "var(--accent-teal)" }}>✦ {cal.special_working_days.length} special working day(s)</span>
      )}
    </div>
  );
}

/** Compact all-months overview (optional) — kept for a quick year scan. */
export function MonthCompact({
  y, m0, calendar, asOf, events, onOpenMonth,
}: {
  y: number;
  m0: number;
  calendar: HolidayCalendar | null;
  asOf: string;
  events: Map<string, Evt[]>;
  onOpenMonth: (ref: MonthRef) => void;
}) {
  const cells = useMemo(() => monthDays(y, m0), [y, m0]);
  const total = cells.reduce((n, iso) => n + (iso ? (events.get(iso)?.length || 0) : 0), 0);
  return (
    <div className="cal-compact">
      <button className="cal-compact-head" onClick={() => onOpenMonth({ y, m0 })}>
        <span>{monthLabel(y, m0)}</span>
        <span className="muted">{ total } event{total === 1 ? "" : "s"}</span>
      </button>
      <div className="cal-grid cal-grid-sm">
        {DOW.map((d) => <div key={d} className="cal-dow cal-dow-sm">{d[0]}</div>)}
        {cells.map((iso, i) => {
          if (!iso) return <div key={i} className="cal-cell-sm empty" />;
          const f = dayFlags(calendar, iso, asOf);
          const n = (events.get(iso) || []).length;
          const cls = ["cal-cell-sm"];
          if (f.isHoliday) cls.push("holiday");
          else if (!f.isWorking) cls.push("nonwork");
          if (f.isToday) cls.push("today");
          if (n) cls.push("has-events");
          return (
            <div key={i} className={cls.join(" ")} title={`${fmtDate(iso)} · ${n} event(s)`}>
              <span>{parseISO(iso)!.getDate()}</span>
              {n > 0 && <span className="cal-cell-sm-dot" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
