import AlertsPanel from "../components/AlertsPanel";
import OwnerWorkloadTable from "../components/OwnerWorkloadTable";
import type { AlertItem, AlertSummary, OwnersBlock } from "../types";

export default function Alerts({
  alerts, summary, owners, onSelect, onCopyDigest, digestBusy,
}: {
  alerts: AlertItem[];
  summary: AlertSummary;
  owners: OwnersBlock;
  onSelect: (code: string) => void;
  onCopyDigest: () => void;
  digestBusy?: boolean;
}) {
  return (
    <div className="stack">
      <div className="card-head">
        <div>
          <div className="card-title">Alerts &amp; escalation</div>
          <div className="card-sub">
            Every milestone needing attention, ranked by severity then working-days open, with the
            owner and the escalation target (L1 owner → L2 department manager → L3 Merchandising Manager / Director).
          </div>
        </div>
        {summary.max_escalation > 0 && (
          <span className="badge badge-error">max escalation L{summary.max_escalation}</span>
        )}
      </div>

      <AlertsPanel
        alerts={alerts}
        summary={summary}
        onSelect={onSelect}
        onCopyDigest={onCopyDigest}
        digestBusy={digestBusy}
      />

      <div className="card-head" style={{ marginTop: 8 }}>
        <div className="card-title">Owner workload</div>
        <div className="card-sub">Open milestones and exposure per owner (assigned name, else the template role).</div>
      </div>
      <OwnerWorkloadTable block={owners} />
    </div>
  );
}
