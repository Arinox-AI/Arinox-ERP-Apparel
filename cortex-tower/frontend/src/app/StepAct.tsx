import { useState } from "react";
import type { ReactNode } from "react";
import { Btn, Modal, Note, call, useToast } from "./kit";
import type { R } from "./kit";

/* The preview -> confirm pattern of every Order-page action (ORDER_TO_SHIP_PLAN section 3 rule 3): the first call runs with `preview: true` and
   writes nothing; the modal says what the ERP would do; Confirm repeats the call for real. A risky class (making purchase orders) answers
   `needs_approval`: the modal then says who has to approve and keeps the approval number so the same action can be run again. */
export function useAct(onDone: () => void) {
  const toast = useToast();
  const [pend, setPend] = useState<{ fn: string; params: R; title: string; res: R; lines?: ReactNode } | null>(null);
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState<number | null>(null);

  const ask = async (fn: string, params: R, title: string, lines?: ReactNode) => {
    setBusy(true);
    const res = await call(fn, { ...params, preview: true });
    setBusy(false);
    if (res.needs_approval) { setApproval(res.approval_id || null); setPend({ fn, params: { ...params, approval_id: res.approval_id }, title, res, lines }); return; }
    if (!res.ok) { toast(res.error || "The ERP refused it.", "bad"); return; }
    setPend({ fn, params, title, res, lines });
  };
  const confirm = async () => {
    if (!pend) return;
    setBusy(true);
    const res = await call(pend.fn, { ...pend.params, preview: false });
    setBusy(false);
    if (res.needs_approval) {
      toast(`A manager must approve this first (approval #${res.approval_id}).`, "bad"); setApproval(res.approval_id || null);
      setPend({ ...pend, params: { ...pend.params, approval_id: res.approval_id }, res: { ...pend.res, needs_approval: true, approval_id: res.approval_id } });   // the next Confirm carries the approval, not a new request
      return;
    }
    if (!res.ok) { toast(res.error || "The ERP refused it.", "bad"); return; }
    setPend(null); setApproval(null);
    toast(res.name ? `Done: ${res.name}` : Array.isArray(res.made) && res.made.length ? `Made ${res.made.join(", ")}` : "Done.");
    onDone();
  };
  const ops = (r: R): R[] => (Array.isArray(r.preview) ? r.preview.flatMap((p: R) => p?.operations || []) : r.preview?.operations || []);
  const modal = pend && (
    <Modal title={pend.title} sub="This is what the ERP will do. Nothing has been written yet." onClose={() => setPend(null)}
      foot={<><Btn onClick={() => setPend(null)}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={!!pend.res.needs_approval && !approval} onClick={confirm}>{pend.res.needs_approval ? "Run after approval" : "Confirm"}</Btn></>}>
      {pend.res.needs_approval && <Note tone="warn">A manager must approve this before it runs (approval #{pend.res.approval_id}). When it is approved, press the button again.</Note>}
      {pend.lines}
      {Array.isArray(pend.res.planned) && pend.res.planned.length > 0 && <div className="ws-stack" style={{ gap: 2 }}>
        <div className="ws-small"><b>{pend.res.planned.length} to make</b></div>
        {pend.res.planned.map((x: R, i: number) => <div key={i} className="ws-small ws-muted">{[x.sample_type, x.style_item, x.colour].filter(Boolean).join(" · ")}</div>)}</div>}
      {ops(pend.res).map((o, i) => <div key={i} className="ws-small ws-muted">{o.op} {o.doctype} {o.name}</div>)}
      {(Array.isArray(pend.res.preview) ? pend.res.preview : [pend.res.preview]).flatMap((p: R) => p?.warnings || []).map((w: string, i: number) => <Note key={i} tone="warn">{w}</Note>)}
    </Modal>);
  return { ask, modal, busy };
}
