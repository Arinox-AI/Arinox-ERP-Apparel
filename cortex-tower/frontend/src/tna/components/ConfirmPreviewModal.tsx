import StatusBadge from "./StatusBadge";
import RagPill from "./RagPill";
import type { UpdateResult } from "../types";

/**
 * The only path to a write. Displays old → new for every changed field, plus the
 * before/after status and RAG, and confirms the write target (local overlay, no
 * ERP write).
 */
export default function ConfirmPreviewModal({
  preview, onConfirm, onCancel, busy,
}: {
  preview: UpdateResult;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  return (
    <div className="modal-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Confirm milestone change">
        <div className="modal-head">
          <h3 style={{ fontSize: 18 }}>Confirm change — <span className="mono">{preview.code}</span></h3>
          <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
            Order {preview.order_id} · action <span className="mono">{preview.action_id.slice(0, 8)}</span>
          </div>
        </div>

        <div className="modal-body stack">
          <table className="diff">
            <thead>
              <tr><th>Field</th><th>Current</th><th>New</th></tr>
            </thead>
            <tbody>
              {preview.changes.length === 0 && (
                <tr><td colSpan={3} className="muted">No field changes detected.</td></tr>
              )}
              {preview.changes.map((c) => (
                <tr key={c.field}>
                  <td>{c.field.replace(/_/g, " ")}</td>
                  <td className="old">{c.old || "—"}</td>
                  <td className="new">{c.new || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="grid-2">
            <div className="card card-surface" style={{ padding: 14 }}>
              <div className="ctl-label">Status</div>
              <div className="row" style={{ marginTop: 6 }}>
                <StatusBadge status={preview.status_before || "—"} />
                <span className="muted">→</span>
                <StatusBadge status={preview.status_after || "—"} />
              </div>
            </div>
            <div className="card card-surface" style={{ padding: 14 }}>
              <div className="ctl-label">Overall RAG</div>
              <div className="row" style={{ marginTop: 6 }}>
                <RagPill rag={preview.rag_before || "amber"} />
                <span className="muted">→</span>
                <RagPill rag={preview.rag_after || "amber"} />
              </div>
            </div>
          </div>

          <div className="banner banner-info">
            <span className="banner-icon">🛡</span>
            <div>
              <div className="banner-title">Write target: {preview.write_target || "local_overlay"} · ERP write: {String(preview.erp_write)}</div>
              <div>Mode gate <span className="mono">{preview.mode_gate}</span>. This change is reversible — you can undo it from the Activity tab.</div>
            </div>
          </div>
        </div>

        <div className="modal-foot">
          <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={onConfirm} disabled={busy}>
            {busy ? "Recording…" : "Confirm & record"}
          </button>
        </div>
      </div>
    </div>
  );
}
