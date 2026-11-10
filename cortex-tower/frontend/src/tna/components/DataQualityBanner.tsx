import { useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, X } from "lucide-react";
import type { DataQualityIssue } from "../types";

/**
 * Surfaces `data_quality[]` verbatim from the snapshot (SPEC §5.4). Excluded rows
 * are reported, never silently "fixed".
 *
 * Kept COMPACT: the detail list is collapsed by default and the whole notice can
 * be dismissed (the dismissal is remembered for the session, and re-appears only
 * if the set of flagged issues changes).
 */
export default function DataQualityBanner({ issues }: { issues: DataQualityIssue[] | null | undefined }) {
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);

  const list = issues || [];
  const sig = useMemo(() => list.map((q) => `${q.issue}|${q.affected_code || ""}`).join("§"), [list]);

  if (list.length === 0 || dismissed === sig) return null;

  const first = list[0];

  return (
    <div className="banner banner-snapshot dq-banner">
      <AlertTriangle size={15} className="banner-icon" />
      <div className="dq-body">
        <div className="dq-title">
          <span>
            <b>Data quality</b> — {list.length} issue{list.length === 1 ? "" : "s"} flagged in the source (not corrected)
          </span>
          <button className="dq-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {open ? "Hide details" : "Details"}
          </button>
        </div>
        {!open && (
          <div className="dq-one">
            {first.issue}
            {first.affected_code ? <> <span className="mono">({first.affected_code})</span></> : null}
          </div>
        )}
        {open && (
          <ul className="dq-list">
            {list.map((q, i) => (
              <li key={i}>
                {q.issue}
                {q.affected_code ? <> <span className="mono">({q.affected_code})</span></> : null}
                {q.erp_note ? <> — <span className="secondary">{q.erp_note}</span></> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
      <button className="dq-close" onClick={() => setDismissed(sig)} title="Dismiss" aria-label="Dismiss">
        <X size={15} />
      </button>
    </div>
  );
}
