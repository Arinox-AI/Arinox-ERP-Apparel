import StatusBadge from "./StatusBadge";
import { fmtDate, fmtWdays } from "../lib/format";
import type { ExceptionRow, TnaNextAction } from "../types";

function sev(status: string): "red" | "amber" | "muted" {
  if (status === "Overdue" || status === "Blocked") return "red";
  if (status === "At risk" || status === "Waiting for approval" || status === "Waiting for material") return "amber";
  return "muted";
}

function ExceptionCard({ rank, e, onSelect }: { rank: number; e: ExceptionRow; onSelect: (code: string) => void }) {
  return (
    <div className={`exc-card sev-${sev(e.status)}`}>
      <div className="exc-rank">{rank}</div>
      <div>
        <div className="row" style={{ gap: 8 }}>
          <span className="exc-name">{e.name}</span>
          <span className="mono muted" style={{ fontSize: 12 }}>{e.code}</span>
          {e.is_critical && <span className="badge badge-primary" title="Critical path">◆</span>}
        </div>
        <div className="exc-meta">
          <span>{e.category}</span>
          <span>·</span>
          <span>owner {e.owner || e.owner_role}</span>
          <span>·</span>
          <span>planned {fmtDate(e.planned_finish)}</span>
          {e.actual_finish
            ? <><span>·</span><span>actual {fmtDate(e.actual_finish)}</span><span>·</span><span>{fmtWdays(e.delay_days)}</span></>
            : null}
        </div>
        <div className="exc-action">{e.next_action_text}</div>
      </div>
      <div className="stack-sm" style={{ alignItems: "flex-end" }}>
        <StatusBadge status={e.status} />
        <span className="badge badge-mono" title="Rank reason">{e.rank_reason}</span>
        <button className="btn btn-ghost btn-sm" onClick={() => onSelect(e.code)}>Open ▸</button>
      </div>
    </div>
  );
}

export default function ExceptionPanel({
  exceptions, nextAction, onSelect,
}: {
  exceptions: ExceptionRow[];
  nextAction: TnaNextAction | null;
  onSelect: (code: string) => void;
}) {
  return (
    <div className="stack">
      {nextAction && (
        <div className="exc-next">
          <div className="ctl-label">Next action (top-ranked exception)</div>
          <div className="row" style={{ gap: 8, marginTop: 4 }}>
            <span className="mono" style={{ fontWeight: 600, color: "var(--primary)" }}>{nextAction.code}</span>
            <span style={{ fontWeight: 600 }}>{nextAction.name}</span>
            <StatusBadge status={nextAction.status} showDot={false} />
          </div>
          <div style={{ marginTop: 6, fontSize: 14 }}>{nextAction.next_action_text}</div>
        </div>
      )}

      {exceptions.length === 0 ? (
        <div className="empty">
          <div className="empty-title">No exceptions</div>
          <div>No overdue, at-risk, blocked or unrecorded milestones in this run.</div>
        </div>
      ) : (
        <>
          <div className="card-head">
            <div className="card-title">Ranked exceptions ({exceptions.length})</div>
            <div className="card-sub">Order: Blocked → Overdue → At risk → Not recorded, then largest delay</div>
          </div>
          <div className="exc-list">
            {exceptions.map((e, i) => (
              <ExceptionCard key={e.code} rank={i + 1} e={e} onSelect={onSelect} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
