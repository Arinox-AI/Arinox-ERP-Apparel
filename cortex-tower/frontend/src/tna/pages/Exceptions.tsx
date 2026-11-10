import ExceptionPanel from "../components/ExceptionPanel";
import type { ExceptionRow, TnaNextAction } from "../types";

export default function Exceptions({
  exceptions, nextAction, onSelect,
}: {
  exceptions: ExceptionRow[];
  nextAction: TnaNextAction | null;
  onSelect: (code: string) => void;
}) {
  return (
    <div className="stack">
      <div className="card-head">
        <div>
          <div className="card-title">Exceptions</div>
          <div className="card-sub">
            Overdue, at-risk, blocked, awaiting-approval and unrecorded milestones, ranked by (status, delay, sequence) with the next action.
          </div>
        </div>
        <span className="badge badge-error">{exceptions.length} open</span>
      </div>
      <ExceptionPanel exceptions={exceptions} nextAction={nextAction} onSelect={onSelect} />
    </div>
  );
}
