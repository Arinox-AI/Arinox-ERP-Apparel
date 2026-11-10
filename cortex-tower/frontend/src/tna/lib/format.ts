// Presentation-only formatting helpers. Never used to derive "truth" — the
// backend is authoritative for statuses, delays and KPIs (SPEC §13.4).

export const DASH = "—";

/** ISO date (YYYY-MM-DD) or null → pretty date; null → em-dash. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = parseISO(iso);
  if (!d) return DASH;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** Short date e.g. "07 Nov 25". */
export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = parseISO(iso);
  if (!d) return DASH;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso.replace(" ", "T"));
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return DASH;
  return n.toLocaleString("en-GB");
}

export function fmtNum(n: number | null | undefined, dp = 2): string {
  if (n === null || n === undefined || isNaN(n)) return DASH;
  return n.toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

export function fmtMoney(n: number | null | undefined, currency: string | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return DASH;
  const c = currency || "USD";
  try {
    return n.toLocaleString("en-GB", { style: "currency", currency: c, maximumFractionDigits: 2 });
  } catch {
    return `${c} ${fmtNum(n)}`;
  }
}

/** Signed working-day value: "+4 wd", "−25 wd", "0 wd". (Uses the minus sign.) */
export function fmtWdays(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return DASH;
  if (n === 0) return "0 wd";
  return `${n > 0 ? "+" : "−"}${Math.abs(n)} wd`;
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return DASH;
  return `${n}%`;
}

export function fmtDays(n: number | null | undefined): string {
  if (n === null || n === undefined || isNaN(n)) return DASH;
  return String(n);
}

export function parseISO(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  if (isNaN(d.getTime())) return null;
  return d;
}

export function toISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function todayISO(): string {
  return toISO(new Date());
}

export function addDaysISO(iso: string, n: number): string {
  const d = parseISO(iso);
  if (!d) return iso;
  d.setDate(d.getDate() + n);
  return toISO(d);
}

export function monthLabel(year: number, month0: number): string {
  return new Date(year, month0, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

export function dayName(d: Date): string {
  return d.toLocaleDateString("en-GB", { weekday: "short" });
}

/** Map a status string to its RAG tone (presentation only). */
export function statusTone(status: string): "red" | "amber" | "green" | "muted" | "navy" | "teal" {
  switch (status) {
    case "Completed": return "green";
    case "Completed late": return "amber";
    case "Overdue": return "red";
    case "Blocked": return "red";
    case "At risk": return "amber";
    case "Waiting for approval":
    case "Waiting for material": return "amber";
    case "In progress": return "navy";
    case "Not started": return "muted";
    case "Not recorded": return "muted";
    default: return "muted";
  }
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
