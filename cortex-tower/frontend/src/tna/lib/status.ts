// Cortex TnA Calendar — single source of truth for status → colour/label.
// Used by the Gantt, the Board, the status band, the drawer and the rail so that a
// "Late" milestone is the same red everywhere.

import type { Rag } from "../types";

export type Tone = "green" | "amber" | "red" | "navy" | "teal" | "grey";

/** Map a 10-value status to its semantic tone. */
export function statusTone(status: string | null | undefined): Tone {
  switch ((status || "").trim()) {
    case "Completed":
      return "navy";
    case "Completed late":
      return "amber";
    case "In progress":
      return "teal";
    case "Overdue":
    case "Blocked":
      return "red";
    case "At risk":
    case "Waiting for approval":
    case "Waiting for material":
      return "amber";
    case "Not recorded":
      return "grey";
    case "Not started":
    default:
      return "grey";
  }
}

/** CSS custom-property colour for a tone. */
export function toneColor(t: Tone): string {
  switch (t) {
    case "green": return "var(--success)";
    case "amber": return "var(--warning)";
    case "red": return "var(--error)";
    case "navy": return "var(--primary)";
    case "teal": return "var(--accent-teal)";
    case "grey":
    default: return "var(--text-muted)";
  }
}

/** Light background for a tone. */
export function toneBg(t: Tone): string {
  switch (t) {
    case "green": return "var(--success-light)";
    case "amber": return "var(--warning-light)";
    case "red": return "var(--error-light)";
    case "navy": return "var(--primary-light)";
    case "teal": return "var(--accent-teal-light)";
    case "grey":
    default: return "var(--surface)";
  }
}

export function ragTone(rag: Rag | null | undefined): Tone {
  return rag === "red" ? "red" : rag === "amber" ? "amber" : rag === "green" ? "green" : "grey";
}

/** Short, human label used in pills (keeps the vocabulary but reads well). */
export function statusShort(status: string | null | undefined): string {
  const s = (status || "").trim();
  if (s === "Completed late") return "Done late";
  if (s === "Waiting for approval") return "Awaiting approval";
  if (s === "Waiting for material") return "Awaiting material";
  if (s === "Not recorded") return "Not recorded";
  return s || "—";
}
