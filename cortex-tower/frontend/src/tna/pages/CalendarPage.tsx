import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, CalendarDays, Grid3x3 } from "lucide-react";
import { CalendarLegend, MonthCompact, MonthGrid, buildEventMap, type MonthRef } from "../components/MonthCalendar";
import DayDetailPanel from "../components/DayDetailPanel";
import { fmtDate, monthLabel, parseISO } from "../lib/format";
import type { HolidayCalendar, TnaMilestone } from "../types";

/**
 * The month window ALWAYS includes the as-of ("today") month, so the calendar is
 * anchored on the current date and the "Today" button always has a target. The
 * window runs continuously from the earliest plan date to the later of the last
 * plan date and today.
 */
function monthsInWindow(milestones: TnaMilestone[], shipDate: string | null, asOf: string): MonthRef[] {
  const dates: string[] = [];
  milestones.forEach((m) => {
    [m.planned_start, m.planned_finish, m.actual_start, m.actual_finish].forEach((d) => { if (d) dates.push(d); });
  });
  if (shipDate) dates.push(shipDate);
  if (asOf) dates.push(asOf);
  if (dates.length === 0) return [];
  dates.sort();
  const start = parseISO(dates[0])!;
  const end = parseISO(dates[dates.length - 1])!;
  const out: MonthRef[] = [];
  const cur = new Date(start.getFullYear(), start.getMonth(), 1);
  const last = new Date(end.getFullYear(), end.getMonth(), 1);
  while (cur.getTime() <= last.getTime() && out.length < 48) {
    out.push({ y: cur.getFullYear(), m0: cur.getMonth() });
    cur.setMonth(cur.getMonth() + 1);
  }
  return out;
}

/** The plan's own window (excludes "today"), used for the explanatory hint. */
function planWindow(milestones: TnaMilestone[], shipDate: string | null): { first: string; last: string } | null {
  const dates: string[] = [];
  milestones.forEach((m) => {
    [m.planned_start, m.planned_finish, m.actual_start, m.actual_finish].forEach((d) => { if (d) dates.push(d); });
  });
  if (shipDate) dates.push(shipDate);
  if (dates.length === 0) return null;
  dates.sort();
  return { first: dates[0], last: dates[dates.length - 1] };
}

export default function CalendarPage({
  milestones, shipDate, asOf, holidayCalendars, activeCalendarId, onSelect,
}: {
  milestones: TnaMilestone[];
  shipDate: string | null;
  asOf: string;
  holidayCalendars: Record<string, HolidayCalendar>;
  activeCalendarId: string;
  onSelect: (code: string) => void;
}) {
  const available = Object.keys(holidayCalendars);
  const [pick, setPick] = useState(activeCalendarId);
  const cal = holidayCalendars[pick] || holidayCalendars[activeCalendarId] || null;

  const months = useMemo(() => monthsInWindow(milestones, shipDate, asOf), [milestones, shipDate, asOf]);
  const plan = useMemo(() => planWindow(milestones, shipDate), [milestones, shipDate]);
  const events = useMemo(() => buildEventMap(milestones, shipDate), [milestones, shipDate]);

  const todayRef: MonthRef = useMemo(() => {
    const d = parseISO(asOf) || new Date();
    return { y: d.getFullYear(), m0: d.getMonth() };
  }, [asOf]);

  const todayInsidePlan = !!plan && asOf >= plan.first && asOf <= plan.last;

  const [mode, setMode] = useState<"month" | "scan">("month");
  // Default to the CURRENT month (today), which the window now always contains.
  const [idx, setIdx] = useState(() => {
    const i = months.findIndex((m) => m.y === todayRef.y && m.m0 === todayRef.m0);
    return i >= 0 ? i : 0;
  });
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const cur = months[idx] || months[0] || todayRef;

  // If the clock rolls over a month while the tab is open and the user was parked
  // on the "today" month, follow it to the new current month. (If they had
  // navigated elsewhere, leave their view alone — just mark the new today.)
  const lastToday = useRef(todayRef);
  useEffect(() => {
    const prev = lastToday.current;
    const changed = prev.y !== todayRef.y || prev.m0 !== todayRef.m0;
    if (!changed) return;
    const curM = months[idx];
    const wasOnToday = !!curM && curM.y === prev.y && curM.m0 === prev.m0;
    const i = months.findIndex((m) => m.y === todayRef.y && m.m0 === todayRef.m0);
    if (wasOnToday && i >= 0) { setIdx(i); setSelectedDay(null); }
    lastToday.current = todayRef;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [todayRef.y, todayRef.m0]);
  const go = (delta: number) => { setSelectedDay(null); setIdx((i) => Math.min(Math.max(i + delta, 0), months.length - 1)); };
  const jumpToday = () => {
    const i = months.findIndex((m) => m.y === todayRef.y && m.m0 === todayRef.m0);
    if (i >= 0) { setIdx(i); setSelectedDay(asOf); setMode("month"); }
  };
  const goToPlanStart = () => {
    if (!plan) return;
    const d = parseISO(plan.first);
    if (!d) return;
    const i = months.findIndex((m) => m.y === d.getFullYear() && m.m0 === d.getMonth());
    if (i >= 0) { setIdx(i); setSelectedDay(null); setMode("month"); }
  };

  const monthSummary = useMemo(() => {
    let planned = 0, actual = 0, ship = 0;
    const prefix = `${cur.y}-${String(cur.m0 + 1).padStart(2, "0")}`;
    events.forEach((list, iso) => {
      if (!iso.startsWith(prefix)) return;
      list.forEach((e) => { if (e.kind === "planned") planned++; else if (e.kind === "actual") actual++; else ship++; });
    });
    return { label: monthLabel(cur.y, cur.m0), planned, actual, ship, total: planned + actual + ship };
  }, [events, cur]);

  const dayEvents = selectedDay ? (events.get(selectedDay) || []) : [];

  return (
    <div className="stack">
      <div className="card cal-toolbar-card">
        <div className="cal-toolbar">
          <div className="cal-toolbar-left">
            <CalendarDays size={18} />
            <div>
              <div className="card-title">Order calendar</div>
              <div className="card-sub">Planned finishes, actual finishes, ship dates and site holidays — one month at a time.</div>
            </div>
          </div>
          <div className="cal-toolbar-right">
            <div className="pill-tabs" role="tablist" aria-label="Calendar site">
              {(available.length ? available : [activeCalendarId]).map((c) => (
                <button key={c} className={c === pick ? "on" : ""} onClick={() => setPick(c)} title={holidayCalendars[c]?.label}>
                  {c.replace("_FACTORY", "").replace("_OFFICE", "")}
                </button>
              ))}
            </div>
            <div className="seg">
              <button className={`seg-btn${mode === "month" ? " active" : ""}`} onClick={() => setMode("month")}>
                <CalendarDays size={14} /> Month
              </button>
              <button className={`seg-btn${mode === "scan" ? " active" : ""}`} onClick={() => setMode("scan")}>
                <Grid3x3 size={14} /> Scan
              </button>
            </div>
          </div>
        </div>

        {mode === "month" && (
          <>
            <div className="cal-nav">
              <button className="icon-btn" onClick={() => go(-1)} disabled={idx <= 0} title="Previous month" aria-label="Previous month">
                <ChevronLeft size={18} />
              </button>
              <select
                className="input cal-month-select"
                value={idx}
                onChange={(e) => { setSelectedDay(null); setIdx(Number(e.target.value)); }}
                aria-label="Month"
              >
                {months.map((m, i) => {
                  const isToday = m.y === todayRef.y && m.m0 === todayRef.m0;
                  return <option key={i} value={i}>{monthLabel(m.y, m.m0)}{isToday ? "  ← today" : ""}</option>;
                })}
              </select>
              <button className="icon-btn" onClick={() => go(1)} disabled={idx >= months.length - 1} title="Next month" aria-label="Next month">
                <ChevronRight size={18} />
              </button>
              <button className="btn btn-ghost btn-sm" onClick={jumpToday} disabled={months.length === 0}>Today</button>
              <span className="muted cal-nav-count">{idx + 1} of {months.length} months</span>
            </div>

            <div className="cal-note">
              {todayInsidePlan
                ? <>Today <b>{fmtDate(asOf)}</b> falls inside this order's plan window{plan ? <> ({fmtDate(plan.first)} – {fmtDate(plan.last)})</> : null}.</>
                : <>Today is <b>{fmtDate(asOf)}</b> — <b>outside</b> this order's plan window{plan ? <> ({fmtDate(plan.first)} – {fmtDate(plan.last)})</> : null}. “Today” jumps to the current month.</>}
              {!todayInsidePlan && plan && (
                <button className="btn btn-ghost btn-sm" onClick={goToPlanStart}>Go to plan start</button>
              )}
            </div>
          </>
        )}
      </div>

      {mode === "month" ? (
        <div className="cal-layout">
          <div className="cal-main">
            {monthSummary.total === 0 && (
              <div className="cal-empty-month">
                No milestones fall in <b>{monthSummary.label}</b>.
                {plan ? <> This order's plan runs <b>{fmtDate(plan.first)}</b> – <b>{fmtDate(plan.last)}</b>.</> : null}
                {plan && <button className="btn btn-ghost btn-sm" onClick={goToPlanStart}>Go to plan start</button>}
              </div>
            )}
            <MonthGrid
              y={cur.y} m0={cur.m0} calendar={cal} asOf={asOf} events={events}
              onSelect={onSelect} selectedDay={selectedDay} onSelectDay={(iso) => setSelectedDay(iso)}
            />
            <CalendarLegend cal={cal} />
          </div>
          <DayDetailPanel
            day={selectedDay}
            events={dayEvents}
            milestones={milestones}
            calendar={cal}
            asOf={asOf}
            monthSummary={monthSummary}
            onSelect={onSelect}
            onClear={() => setSelectedDay(null)}
          />
        </div>
      ) : (
        <>
          <div className="cal-compact-wrap">
            {months.map((m) => (
              <MonthCompact key={`${m.y}-${m.m0}`} y={m.y} m0={m.m0} calendar={cal} asOf={asOf} events={events}
                onOpenMonth={(ref) => { const i = months.findIndex((x) => x.y === ref.y && x.m0 === ref.m0); setIdx(i >= 0 ? i : 0); setMode("month"); }} />
            ))}
          </div>
          <CalendarLegend cal={cal} />
        </>
      )}
    </div>
  );
}
