import { useState } from "react";
import { ExternalLink, Link2 } from "lucide-react";
import { fmtDate, fmtInt } from "../lib/format";
import { toneColor } from "../lib/status";
import type { BridgeStatus, IntakeNotification, IntakeSummary } from "../types";

/**
 * BridgeChip — shows the Cortex Tower link. When a Tower app URL is configured it is
 * a one-click jump; when it is not, it offers a tiny form to paste the URL once.
 */
function BridgeChip({
  bridge, onSaveUrl, saving,
}: {
  bridge: BridgeStatus | null;
  onSaveUrl: (url: string) => void;
  saving?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [val, setVal] = useState("");
  if (!bridge) return null;
  const jump = bridge.tower_jump_enabled && bridge.tower_app_url;

  return (
    <div className="bridge-wrap">
      <div className="bridge-chip" title={bridge.note}>
        <span className="bridge-dot" style={{ background: bridge.tower_configured ? "var(--accent-teal)" : "var(--text-muted)" }} />
        <span>
          {bridge.tower_configured ? "Cortex Tower linked" : "Tower offline"}
          <span className="muted"> · {bridge.tower_project}</span>
        </span>

        {jump ? (
          <a className="bridge-jump" href={bridge.tower_app_url as string} target="_blank" rel="noreferrer">
            Open in Cortex Tower <ExternalLink size={12} />
          </a>
        ) : (
          <button className="bridge-jump ghost" onClick={() => setOpen((v) => !v)}>
            <Link2 size={12} /> Add Tower link
          </button>
        )}
      </div>

      {!jump && open && (
        <div className="bridge-form">
          <div className="muted">Paste the URL where the Cortex Tower app is served. Saved once — the jump then appears everywhere.</div>
          <div className="bridge-form-row">
            <input
              className="input"
              placeholder="https://…/cortex-operations-control-tower"
              value={val}
              onChange={(e) => setVal(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && val.trim()) onSaveUrl(val.trim()); }}
            />
            <button className="btn btn-primary btn-sm" disabled={!val.trim() || saving} onClick={() => onSaveUrl(val.trim())}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** One notification card: the order + what the Tower already knows + the actions. */
function NotifCard({
  n, busy, onApprove, onReject, onSnooze, onOpen,
}: {
  n: IntakeNotification;
  busy: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onSnooze: (id: string) => void;
  onOpen: (id: string) => void;
}) {
  const tc = n.tower_context;
  const risks = tc?.tower_risk_count || 0;
  const decided = n.status !== "detected";
  return (
    <div className={`notif-card${decided ? " decided" : ""}`} style={{ borderLeftColor: decided ? toneColor("grey") : toneColor("amber") }}>
      <div className="notif-top">
        <span className="notif-title">{n.customer || "New order"}</span>
        {!decided && <span className="notif-badge">New order</span>}
        {decided && <span className={`notif-state state-${n.status}`}>{n.status}</span>}
      </div>
      <div className="notif-sub">
        <span className="mono">{n.order_id}</span> · {n.style_no || "—"}{n.style_name ? ` · ${n.style_name}` : ""}
      </div>
      <div className="notif-facts">
        <span><span className="muted">Qty</span> <span className="mono">{fmtInt(n.qty)}</span></span>
        <span><span className="muted">Ship</span> <span className="mono">{fmtDate(n.ship_date)}</span></span>
        {tc?.tower_status && <span><span className="muted">Tower</span> {tc.tower_status}</span>}
        {risks > 0 && <span className="notif-risks">⚠ {risks} Tower risk{risks > 1 ? "s" : ""}</span>}
      </div>
      {tc?.tower_risk_titles && tc.tower_risk_titles.length > 0 && (
        <ul className="notif-risks-list">
          {tc.tower_risk_titles.slice(0, 3).map((r, i) => (
            <li key={i}><span className={`sev sev-${r.severity || "warning"}`} /> {r.title}</li>
          ))}
        </ul>
      )}
      <div className="notif-actions">
        {!decided ? (
          <>
            <button className="btn btn-primary" disabled={busy} onClick={() => onApprove(n.order_id)}>
              {busy ? "Starting…" : "Approve & start TnA"}
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => onSnooze(n.order_id)}>Later</button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => onReject(n.order_id)}>Dismiss</button>
          </>
        ) : (
          <button className="btn btn-ghost" onClick={() => onOpen(n.order_id)}>Open plan</button>
        )}
        {n.tower_link && (
          <a className="btn btn-ghost" href={n.tower_link} target="_blank" rel="noreferrer">
            Cortex Tower <ExternalLink size={13} />
          </a>
        )}
      </div>
    </div>
  );
}

/**
 * IntakePanel — the new-order inbox. Orders arrive from the ERP and are enriched
 * with what the Cortex Tower already knows (status, open risks). "Approve & start
 * TnA" is what kicks off the plan for that order.
 */
export default function IntakePanel({
  notifications, summary, bridge, busyId, onApprove, onReject, onSnooze, onOpen, error,
  onSaveTowerUrl, savingUrl,
}: {
  notifications: IntakeNotification[];
  summary: IntakeSummary | null;
  bridge: BridgeStatus | null;
  busyId: string | null;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onSnooze: (id: string) => void;
  onOpen: (id: string) => void;
  error?: string | null;
  onSaveTowerUrl: (url: string) => void;
  savingUrl?: boolean;
}) {
  const pending = notifications.filter((n) => n.status === "detected");
  const decided = notifications.filter((n) => n.status !== "detected");

  return (
    <div className="intake-panel">
      <div className="intake-head">
        <div>
          <div className="intake-title">New orders &amp; notifications</div>
          <div className="intake-sub muted">
            {summary ? `${summary.pending} awaiting approval · ${summary.approved} in the book` : "Loading…"}
          </div>
        </div>
        <BridgeChip bridge={bridge} onSaveUrl={onSaveTowerUrl} saving={savingUrl} />
      </div>

      <div className="intake-body">
        {error && (
          <div className="intake-error">
            <strong>Notifications unavailable.</strong> {error}
            {/not found\.\s*Available:/i.test(error) && (
              <span> The backend needs to be (re)published to expose the intake functions.</span>
            )}
          </div>
        )}
        <div className="intake-group-label">
          {pending.length ? `Awaiting your approval · ${pending.length}` : "Nothing awaiting approval"}
        </div>
        {pending.length === 0 && (
          <div className="intake-empty">
            When a new order arrives it lands here. Approving it starts that order's TnA plan.
          </div>
        )}
        {pending.map((n) => (
          <NotifCard key={n.order_id} n={n} busy={busyId === n.order_id}
            onApprove={onApprove} onReject={onReject} onSnooze={onSnooze} onOpen={onOpen} />
        ))}

        {decided.length > 0 && (
          <>
            <div className="intake-group-label">Already in the book · {decided.length}</div>
            {decided.slice(0, 20).map((n) => (
              <NotifCard key={n.order_id} n={n} busy={false}
                onApprove={onApprove} onReject={onReject} onSnooze={onSnooze} onOpen={onOpen} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
