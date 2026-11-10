import { useState } from "react";
import { DELAY_CAUSES, STATUS_VOCAB, type TnaMilestone } from "../types";
import { fmtDate } from "../lib/format";

export interface UpdateFormValue {
  actual_start?: string;
  actual_finish?: string;
  revised_finish?: string;
  delay_reason?: string;
  owner?: string;
  note?: string;
  status_override?: string;
}

const CLEAR = "__clear__";

/**
 * Preview-first update form. It never writes: it collects a diff and hands it to
 * the parent, which opens the ConfirmPreviewModal (the ONLY path to a write).
 * Blank fields are omitted from the payload = "unchanged" (the backend never
 * silently wipes a recorded value). An explicit Clear sends the "__clear__"
 * sentinel.
 */
export default function UpdateMilestoneForm({
  milestone, onSubmit, busy,
}: {
  milestone: TnaMilestone;
  onSubmit: (v: UpdateFormValue) => void;
  busy?: boolean;
}) {
  const [actualStart, setActualStart] = useState("");
  const [actualFinish, setActualFinish] = useState("");
  const [revisedFinish, setRevisedFinish] = useState("");
  const [reason, setReason] = useState("");
  const [customReason, setCustomReason] = useState("");
  const [owner, setOwner] = useState("");
  const [note, setNote] = useState("");
  const [statusOverride, setStatusOverride] = useState("");

  const effReason = reason === "__custom__" ? customReason.trim() : reason;

  const hasChange = !!(
    actualStart || actualFinish || revisedFinish || effReason || owner.trim() || note.trim() || statusOverride
  );

  const submit = () => {
    const v: UpdateFormValue = {};
    if (actualStart) v.actual_start = actualStart;
    if (actualFinish) v.actual_finish = actualFinish;
    if (revisedFinish) v.revised_finish = revisedFinish;
    if (effReason) v.delay_reason = effReason;
    if (owner.trim()) v.owner = owner.trim();
    if (note.trim()) v.note = note.trim();
    if (statusOverride) v.status_override = statusOverride;
    onSubmit(v);
  };

  const ClearDate = ({ onClear, label }: { onClear: () => void; label: string }) => (
    <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start", padding: "2px 6px" }} onClick={onClear} title={`Clear ${label}`}>
      Clear
    </button>
  );

  return (
    <div className="stack-sm">
      <div className="field-grid">
        <div className="field">
          <label htmlFor="um-start">Actual start</label>
          <input id="um-start" type="date" className="input mono" value={actualStart === CLEAR ? "" : actualStart}
            onChange={(e) => setActualStart(e.target.value)}
            placeholder={milestone.actual_start || ""} />
          <div className="field-hint">
            Current: {fmtDate(milestone.actual_start)}
            {milestone.actual_start && <> · <span style={{ color: "var(--error)", cursor: "pointer" }} onClick={() => setActualStart(CLEAR)}>clear</span></>}
          </div>
        </div>
        <div className="field">
          <label htmlFor="um-finish">Actual finish</label>
          <input id="um-finish" type="date" className="input mono" value={actualFinish === CLEAR ? "" : actualFinish}
            onChange={(e) => setActualFinish(e.target.value)}
            placeholder={milestone.actual_finish || ""} />
          <div className="field-hint">
            Current: {fmtDate(milestone.actual_finish)}
            {milestone.actual_finish && <> · <span style={{ color: "var(--error)", cursor: "pointer" }} onClick={() => setActualFinish(CLEAR)}>clear</span></>}
          </div>
        </div>
        <div className="field">
          <label htmlFor="um-revised">Revised finish (re-plan)</label>
          <input id="um-revised" type="date" className="input mono" value={revisedFinish === CLEAR ? "" : revisedFinish}
            onChange={(e) => setRevisedFinish(e.target.value)}
            placeholder={milestone.revised_finish || ""} />
          <div className="field-hint">
            Current: {fmtDate(milestone.revised_finish)}
            {milestone.revised_finish && <> · <span style={{ color: "var(--error)", cursor: "pointer" }} onClick={() => setRevisedFinish(CLEAR)}>clear</span></>}
          </div>
        </div>
        <div className="field">
          <label htmlFor="um-reason">Delay reason</label>
          <select id="um-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">— unchanged —</option>
            {DELAY_CAUSES.map((c) => <option key={c} value={c}>{c}</option>)}
            <option value="__custom__">Other…</option>
          </select>
          {reason === "__custom__" && (
            <input className="input" style={{ marginTop: 4 }} placeholder="Custom reason" value={customReason} onChange={(e) => setCustomReason(e.target.value)} />
          )}
          {milestone.delay_reason && <div className="field-hint">Current: {milestone.delay_reason}</div>}
        </div>
        <div className="field">
          <label htmlFor="um-owner">Owner</label>
          <input id="um-owner" className="input" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder={milestone.owner || milestone.owner_role} />
        </div>
        <div className="field">
          <label htmlFor="um-status">Status override</label>
          <select id="um-status" className="input" value={statusOverride} onChange={(e) => setStatusOverride(e.target.value)}>
            <option value="">— computed ({milestone.status}) —</option>
            <option value={CLEAR}>Clear override</option>
            {STATUS_VOCAB.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div className="field full">
          <label htmlFor="um-note">Note</label>
          <textarea id="um-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional note recorded with the change" />
        </div>
      </div>

      <div className="row between">
        <span className="field-hint">Blank fields are left unchanged. Writes go to the local overlay only — never the ERP.</span>
        <button className="btn btn-primary" onClick={submit} disabled={!hasChange || busy}>
          {busy ? "Preparing…" : "Review change"}
        </button>
      </div>
    </div>
  );
}
