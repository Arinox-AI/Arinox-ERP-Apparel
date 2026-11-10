import { PanelRightClose } from "lucide-react";
import { fmtDate, fmtWdays } from "../lib/format";
import StatusPill from "./StatusPill";
import type { AlertItem, ExceptionRow } from "../types";

/**
 * NeedsAttentionRail — the always-visible "what's late and who owns it" panel.
 * Merges the v1 Exceptions tab and the Alerts tab into one right-hand rail.
 */
export default function NeedsAttentionRail({
  exceptions, alerts, onSelect, onCopyDigest, digestBusy, onClose,
}: {
  exceptions: ExceptionRow[];
  alerts: AlertItem[];
  onSelect: (code: string) => void;
  onCopyDigest?: () => void;
  digestBusy?: boolean;
  onClose?: () => void;
}) {
  const late = exceptions.filter((e) => e.status === "Overdue" || e.status === "Completed late");
  const atRisk = exceptions.filter((e) => e.status !== "Overdue" && e.status !== "Completed late");
  const top = late[0] || atRisk[0] || null;
  const ownerOf = (code: string) => alerts.find((a) => a.code === code)?.assigned_to;

  const Row = ({ e }: { e: ExceptionRow }) => (
    <button className="na-row" onClick={() => onSelect(e.code)}>
      <span className="na-row-top">
        <span className="na-row-name">{e.name}</span>
        <StatusPill status={e.status} />
      </span>
      <span className="na-row-meta">
        <span className="mono">{e.code}</span>
        <span>· {e.owner_role || ownerOf(e.code) || "Unassigned"}</span>
      </span>
      <span className="na-row-bottom">
        <span className="na-due mono">{fmtDate(e.planned_finish)}</span>
        {e.delay_days ? <span className="na-delay">{fmtWdays(e.delay_days)}</span> : null}
      </span>
    </button>
  );

  return (
    <aside className="na-rail" aria-label="Needs attention">
      <div className="na-head">
        <span className="eyebrow">Needs attention</span>
        <span className="rail-head-right">
          <span className="pill-count">{exceptions.length}</span>
          {onClose && (
            <button className="rail-close" onClick={onClose} title="Hide needs-attention panel" aria-label="Hide needs-attention panel">
              <PanelRightClose size={15} />
            </button>
          )}
        </span>
      </div>

      {top && (
        <div className="na-next">
          <div className="na-next-label">Next action</div>
          <div className="na-next-text">{top.next_action_text}</div>
        </div>
      )}

      <div className="na-scroll">
        <div className="na-group">
          <div className="na-group-head">
            <span className="na-dot" style={{ background: "var(--error)" }} /> Late
            <span className="muted"> · {late.length}</span>
          </div>
          {late.length === 0 && <div className="na-empty">Nothing late.</div>}
          {late.slice(0, 12).map((e) => <Row key={e.code} e={e} />)}
        </div>

        <div className="na-group">
          <div className="na-group-head">
            <span className="na-dot" style={{ background: "var(--warning)" }} /> At risk &amp; blocked
            <span className="muted"> · {atRisk.length}</span>
          </div>
          {atRisk.length === 0 && <div className="na-empty">Nothing at risk.</div>}
          {atRisk.slice(0, 12).map((e) => <Row key={e.code} e={e} />)}
        </div>
      </div>

      {onCopyDigest && (
        <button className="btn btn-ghost na-digest" onClick={onCopyDigest} disabled={digestBusy}>
          {digestBusy ? "Preparing…" : "Copy reminder digest"}
        </button>
      )}
    </aside>
  );
}
