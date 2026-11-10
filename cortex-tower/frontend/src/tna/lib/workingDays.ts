// Presentation-only mirror of the backend working-day engine (SPEC §13.4).
// Used to lay out the Gantt/calendar AXES and holiday shading. The backend is
// ALWAYS authoritative for statuses, delays and KPIs — the client never
// re-derives them "for display of truth".

import type { HolidayCalendar } from "../types";
import { parseISO, toISO } from "./format";

export interface DayFlags {
  iso: string;
  weekday: number;      // ISO 1=Mon..7=Sun
  isWeekend: boolean;
  isHoliday: boolean;
  holidayLabel: string | null;
  isWorking: boolean;
  isToday: boolean;
}

export function isHoliday(cal: HolidayCalendar | null, iso: string): string | null {
  if (!cal) return null;
  return cal.holidays[iso] ?? null;
}

export function isWorkingDay(cal: HolidayCalendar | null, iso: string): boolean {
  const d = parseISO(iso);
  if (!d) return false;
  const isoWd = d.getDay() === 0 ? 7 : d.getDay();
  const inWeek = cal ? cal.working_weekdays.includes(isoWd) : isoWd !== 7;
  const special = cal ? cal.special_working_days.includes(iso) : false;
  if (special) return true;
  if (isHoliday(cal, iso)) return false;
  return inWeek;
}

export function dayFlags(cal: HolidayCalendar | null, iso: string, today: string): DayFlags {
  const d = parseISO(iso);
  const isoWd = d ? (d.getDay() === 0 ? 7 : d.getDay()) : 1;
  // "Weekend" for shading purposes = a day in the standard Mon–Fri office week
  // that is not a configured working weekday (for VN_FACTORY that is Sunday).
  const weekend = cal ? !cal.working_weekdays.includes(isoWd) : isoWd === 7;
  const hol = isHoliday(cal, iso);
  return {
    iso,
    weekday: isoWd,
    isWeekend: weekend,
    isHoliday: !!hol,
    holidayLabel: hol,
    isWorking: isWorkingDay(cal, iso),
    isToday: iso === today,
  };
}

/** Signed working-day difference b − a, using the same step rules as the backend. */
export function workingDaysBetween(cal: HolidayCalendar | null, aISO: string, bISO: string): number {
  const a = parseISO(aISO);
  const b = parseISO(bISO);
  if (!a || !b) return 0;
  const diffDays = Math.round((b.getTime() - a.getTime()) / 86400000);
  if (diffDays === 0) return 0;
  const step = diffDays > 0 ? 1 : -1;
  const n = Math.abs(diffDays);
  let count = 0;
  const cur = new Date(a.getTime());
  for (let i = 0; i < n; i++) {
    cur.setDate(cur.getDate() + step);
    if (isWorkingDay(cal, toISO(cur))) count += step;
  }
  return count;
}

/** Inclusive list of ISO days from a to b. */
export function daysBetween(aISO: string, bISO: string): string[] {
  const out: string[] = [];
  const a = parseISO(aISO);
  const b = parseISO(bISO);
  if (!a || !b) return out;
  const cur = new Date(a.getTime());
  // guard against runaway ranges
  const max = 800;
  while (cur.getTime() <= b.getTime() && out.length < max) {
    out.push(toISO(cur));
    cur.setDate(cur.getDate() + 1);
  }
  return out;
}
