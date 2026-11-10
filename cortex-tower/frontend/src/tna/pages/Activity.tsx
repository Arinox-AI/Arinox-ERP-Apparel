import ActionHistoryTable from "../components/ActionHistoryTable";
import AuditLogTable from "../components/AuditLogTable";
import type { ActionRecord, AuditEntry } from "../types";

export default function Activity({
  logs, actions, onRun, onRollback, busyId,
}: {
  logs: AuditEntry[];
  actions: ActionRecord[];
  onRun: (a: ActionRecord) => void;
  onRollback: (a: ActionRecord) => void;
  busyId?: string | null;
}) {
  return (
    <div className="stack">
      <div className="card-head">
        <div>
          <div className="card-title">Write history</div>
          <div className="card-sub">
            Every write targets the local overlay (never the ERP). Staged actions can be run; applied actions can be rolled back.
          </div>
        </div>
        <span className="badge">{actions.length} actions</span>
      </div>
      <ActionHistoryTable actions={actions} onRun={onRun} onRollback={onRollback} busyId={busyId} />

      <div className="card-head" style={{ marginTop: 8 }}>
        <div>
          <div className="card-title">Audit journal</div>
          <div className="card-sub">Append-only. {logs.length} entries, newest first.</div>
        </div>
      </div>
      <AuditLogTable logs={logs} />
    </div>
  );
}
