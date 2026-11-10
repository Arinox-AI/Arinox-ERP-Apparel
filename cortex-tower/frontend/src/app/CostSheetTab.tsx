import { useEffect, useState } from "react";
import { Check, Calculator, ExternalLink, Plus, RefreshCw, Trash2 } from "lucide-react";
import { Btn, Input, Loading, Note, Select, call, money, num, useToast } from "./kit";
import type { R } from "./kit";

/* ───────────────────────── the ERP cost sheet, as a tab ─────────────────────────
   This is the costing the ERP itself holds for one style: the material rows that came out of the Buyer BOM and the ERP's
   own cost heads. It used to open in a modal from the Deals page; it lives here now, as its own tab, so the full costing
   and the ERP's document are one page.

   It FILLS ITSELF from the standard costing sheet (the workbook: a rate on every line, CMT 5.000, rejection 3 %, and
   APPLY 0 on the lines the factory does not use) — that is `deal_cost_autofill`, which also ticks N/A for the heads the
   sheet turns off, because the ERP refuses to submit a costing that leaves a mandatory head at 0 without N/A. What is
   left is a person's changes: a price that is different this season, an N/A that does not apply, then Save & submit.
   The sheet stays a draft until somebody submits it. */

export const MATERIAL_TYPES = ["Fabric", "Lining", "Contrast Fabric", "Trim", "Label", "Packaging", "Thread", "Fusing", "Other"];

export function CostSheetTab({ deal, styleKey, onShowAll, onSaved }: {
  deal: R; styleKey: string; onShowAll?: () => void; onSaved?: () => void;
}) {
  const toast = useToast();
  const [cs, setCs] = useState<R | null>(null);
  const [heads, setHeads] = useState<R[]>([]);
  const [fill, setFill] = useState<R | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [msgs, setMsgs] = useState<string[]>([]);
  const [quoted, setQuoted] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  const style = deal.styles.find((s: R) => s.key === styleKey) || {};
  const ccy = deal.currency || "USD";

  useEffect(() => {
    (async () => {
      // opens the document exactly as the ERP holds it - nothing is written until somebody presses the fill button
      const r = await call("deal_cost_open", { deal_id: deal.id, style_key: styleKey });
      if (!r.ok) { setErr(r.error || "Could not open the costing."); return; }
      setCs(r.cost_sheet); setHeads(r.heads || []);
      setQuoted(r.cost_sheet.totals.quoted_price ? String(r.cost_sheet.totals.quoted_price) : "");
    })();
  }, [deal.id, styleKey]);

  const locked = cs?.docstatus === 1;
  const calcOf = (h: string) => heads.find((x) => x.name === h)?.calc_type || "";
  const unit = (ct: string) => (/percent/i.test(ct) ? "%" : /sam/i.test(ct) ? `${ccy}/min` : /metre/i.test(ct) ? `${ccy}/m` : `${ccy}/pc`);
  const setMat = (i: number, k: string, v: any) => { setDirty(true); setCs((c) => c && { ...c, materials: c.materials.map((m: R, j: number) => (j === i ? { ...m, [k]: v } : m)) }); };
  const setChg = (i: number, k: string, v: any) => { setDirty(true); setCs((c) => c && { ...c, charges: c.charges.map((m: R, j: number) => (j === i ? { ...m, [k]: v } : m)) }); };

  const run = async (mode: "preview" | "save" | "submit") => {
    if (!cs) return;
    setBusy(mode); setErr("");
    if (mode !== "submit" || dirty) {
      const r = await call("deal_cost_save", { deal_id: deal.id, style_key: styleKey, materials: cs.materials, charges: cs.charges,
        quoted_price: quoted === "" ? null : Number(quoted), preview: mode === "preview" });
      if (!r.ok) { setBusy(""); setErr(r.error || "The costing was refused."); return; }
      setCs(r.cost_sheet); setMsgs(r.messages || []);
      if (mode !== "preview") setDirty(false);
      if (mode === "preview") { setBusy(""); return; }
    }
    if (mode === "submit") {
      const r = await call("deal_cost_submit", { deal_id: deal.id, style_key: styleKey });
      setBusy("");
      if (!r.ok) { setErr(r.error || "The ERP refused to submit it."); return; }
      toast(`${style.style_no} costed and submitted at ${money(r.style?.cost?.quoted_price, ccy)}.`);
      onSaved?.();
      return;
    }
    setBusy(""); toast("Costing saved in the ERP."); onSaved?.();
  };
  const t = cs?.totals || {};
  const missing: string[] = fill?.missing || [];
  const unmatched: string[] = fill?.unmatched || [];

  // the button: the sheet's figures onto the ERP document (blanks only, a draft, never a submit)
  const refill = async () => {
    if (dirty) { toast("Save your changes first - the fill reads the document as the ERP holds it.", "bad"); return; }
    setBusy("fill"); setErr("");
    const r = await call("deal_cost_autofill", { deal_id: deal.id, style_key: styleKey });
    setBusy("");
    if (!r.ok) { setErr(r.error || "The ERP refused the fill."); return; }
    setCs(r.cost_sheet); setHeads(r.heads_list || []); setFill(r); setDirty(false);
    toast(r.priced || r.na
      ? `Filled ${r.priced} line(s) and marked ${r.na} head(s) N/A from the costing sheet.`
      : "Nothing left to fill: every line the sheet knows is already priced.", r.priced || r.na ? undefined : "bad");
  };

  if (err) return <Note tone="bad">{err}</Note>;
  if (!cs) return <Loading rows={5} />;

  return (
    <div className="ws-grid ws-grid--side">
      <div className="ws-stack" style={{ gap: 14 }}>
        {!!fill && !locked && (fill.priced > 0 || fill.na > 0) && (
          <Note tone="ok">
            Filled from the standard costing sheet: {fill.priced} line{fill.priced === 1 ? "" : "s"} priced,{" "}
            {fill.na} cost head{fill.na === 1 ? "" : "s"} marked N/A (the lines the sheet switches off).{" "}
            {fill.written ? "Saved as a draft in the ERP - change what is different for this style." : ""}
          </Note>
        )}
        {locked && <Note tone="ok">Submitted in the ERP as {cs.name} - read only here. Amend it in the ERP to change a price.</Note>}
        {!locked && (
          <div className="ws-card" style={{ padding: 12 }}>
            <div className="ws-row ws-row--between" style={{ flexWrap: "wrap", gap: 10 }}>
              <div className="ws-small ws-muted" style={{ flex: "1 1 260px", minWidth: 0 }}>
                Fill the lines that are still at 0 with the costing sheet's own figures - each material's price, each cost
                head's rate, and N/A for the heads the sheet switches off. Nothing else is touched and nothing is submitted.
              </div>
              <Btn sm kind="primary" busy={busy === "fill"} onClick={() => void refill()}><RefreshCw size={13} /> Fill from the costing sheet</Btn>
            </div>
          </div>
        )}
        <div>
          <div className="ws-row ws-row--between" style={{ marginBottom: 6 }}>
            <b>Materials <span className="ws-small ws-muted">({cs.materials.length} lines - the Buyer BOM's items)</span></b>
            {!locked && <Btn sm onClick={() => { setDirty(true); setCs({ ...cs, materials: [...cs.materials, { material_type: "Trim", description: "", consumption: 1, rate: 0, uom: "Nos", is_selected: 1 }] }); }}><Plus size={13} /> Add line</Btn>}
          </div>
          <div className="ws-card ws-table-wrap">
            <table className="ws-table ws-table--edit">
              <thead><tr><th>Type</th><th>Description</th><th className="num">Cons.</th><th>UOM</th><th className="num">Waste %</th><th className="num">Rate</th><th className="num">Amount</th>{!locked && <th />}</tr></thead>
              <tbody>{cs.materials.map((m: R, i: number) => (
                <tr key={i}>
                  <td style={{ width: 120 }}><Select sm value={m.material_type} onChange={(v) => setMat(i, "material_type", v)} options={MATERIAL_TYPES} disabled={locked} /></td>
                  <td><Input sm value={m.description} onChange={(v) => setMat(i, "description", v)} disabled={locked} /></td>
                  <td style={{ width: 80 }}><Input sm num type="number" value={m.consumption ?? ""} onChange={(v) => setMat(i, "consumption", Number(v))} disabled={locked} /></td>
                  <td style={{ width: 70 }} className="ws-small">{m.uom || "—"}</td>
                  <td style={{ width: 80 }}><Input sm num type="number" value={m.wastage_pct == null ? "" : Number(m.wastage_pct) * 100} onChange={(v) => setMat(i, "wastage_pct", v === "" ? 0 : Number(v) / 100)} disabled={locked} /></td>
                  <td style={{ width: 90 }}><Input sm num type="number" value={m.rate ?? ""} onChange={(v) => setMat(i, "rate", Number(v))} disabled={locked} /></td>
                  <td className="num ws-small" style={{ width: 90 }}>{m.amount !== undefined && m.amount !== null ? num(m.amount, 4) : "—"}</td>
                  {!locked && <td style={{ width: 34 }}><Btn sm icon kind="plain" onClick={() => { setDirty(true); setCs({ ...cs, materials: cs.materials.filter((_: R, j: number) => j !== i) }); }}><Trash2 size={13} /></Btn></td>}
                </tr>))}</tbody>
            </table>
          </div>
          {missing.length > 0 && (
            <div className="ws-mt-s"><Note tone="warn">
              No price yet for {missing.length} material line{missing.length === 1 ? "" : "s"}: {missing.join(", ")}. Give
              {missing.length === 1 ? " it" : " them"} a price on the detailed sheet (or here) and press the fill again.
            </Note></div>
          )}
          {cs.materials.some((m: R) => Number(m.wastage_pct) > 0 && !m.wastage_reason) && !locked && <div className="ws-mt-s"><Note tone="warn">The ERP asks for a reason for every wastage %. Add it on the line: {cs.materials.filter((m: R) => Number(m.wastage_pct) > 0 && !m.wastage_reason).map((m: R, i: number) => (
            <span key={i} style={{ display: "block", marginTop: 4 }}>{m.description}: <input className="ws-input ws-input--sm" style={{ width: 240 }} value={m.wastage_reason || ""} onChange={(e) => setMat(cs.materials.indexOf(m), "wastage_reason", e.target.value)} placeholder="e.g. shrinkage after wash" /></span>))}</Note></div>}
        </div>

        <div>
          <div className="ws-row ws-row--between" style={{ marginBottom: 6 }}>
            <b>Cost heads <span className="ws-small ws-muted">(the ERP's own heads - N/A is for the ones this style does not use)</span></b>
          </div>
          <div className="ws-card ws-table-wrap">
            <table className="ws-table ws-table--edit">
              <thead><tr><th>Head</th><th>How</th><th className="num">Rate</th><th>N/A</th><th className="num">Amount</th></tr></thead>
              <tbody>{cs.charges.map((c: R, i: number) => {
                const ct = c.calc_type || calcOf(c.cost_head);
                return (
                  <tr key={c.cost_head} style={{ opacity: c.not_applicable ? 0.55 : 1 }}>
                    <td><b className="ws-small">{c.cost_head}</b></td>
                    <td className="ws-small ws-muted">{ct}</td>
                    <td style={{ width: 130 }}><div className="ws-row" style={{ flexWrap: "nowrap", gap: 4 }}><Input sm num type="number" value={c.rate ?? ""} onChange={(v) => setChg(i, "rate", Number(v))} disabled={locked || !!c.not_applicable} /><span className="ws-small ws-muted ws-nowrap">{unit(ct)}</span></div></td>
                    <td style={{ width: 50 }}><input type="checkbox" checked={!!c.not_applicable} onChange={(e) => setChg(i, "not_applicable", e.target.checked ? 1 : 0)} disabled={locked} aria-label={`${c.cost_head} not applicable`} /></td>
                    <td className="num ws-small">{c.amount !== undefined && c.amount !== null ? num(c.amount, 4) : "—"}</td>
                  </tr>);
              })}</tbody>
            </table>
          </div>
          {unmatched.length > 0 && (
            <div className="ws-mt-s"><Note tone="warn">
              The ERP has cost heads your costing sheet does not cost at all: {unmatched.join(", ")}. Give
              {unmatched.length === 1 ? " it" : " them"} a rate here, or tick N/A - whoever costs this style decides.
            </Note></div>
          )}
          <div className="ws-small ws-muted ws-mt-s">The ERP refuses to submit a costing that leaves a mandatory head at 0 without ticking N/A.</div>
        </div>
      </div>

      <div className="ws-stack" style={{ gap: 12 }}>
        <div className="ws-card" style={{ padding: 14 }}>
          <div className="ws-small ws-muted">Computed price (per piece)</div>
          <div className="ws-price">{money(t.computed_price, ccy, 3)}</div>
          <div className="ws-sum ws-mt">
            <div><span>Fabric</span><b>{num(t.fabric_cost, 4)}</b></div>
            <div><span>Trims & other</span><b>{num(t.trim_cost, 4)}</b></div>
            <div><span>Materials</span><b>{num(t.material_cost, 4)}</b></div>
            <div><span>Conversion & overheads</span><b>{num(t.conversion_cost, 4)}</b></div>
            <div><span>Profit</span><b>{num(t.profit_amount, 4)}</b></div>
            <hr />
            <div><span>Margin at quoted</span><b style={{ color: t.below_floor ? "var(--ws-bad)" : "var(--ws-ok)" }}>{num(t.margin_pct, 2)}%</b></div>
            <div><span>Floor</span><b>{num(t.margin_floor_pct, 1)}%</b></div>
            {t.order_value ? <div><span>Order value</span><b>{money(t.order_value, ccy, 0)}</b></div> : null}
          </div>
        </div>
        {!locked && (
          <div className="ws-card" style={{ padding: 14 }}>
            <div className="ws-small ws-muted" style={{ marginBottom: 4 }}>Price to quote (per piece)</div>
            <div className="ws-row" style={{ flexWrap: "nowrap" }}>
              <Input num type="number" value={quoted} onChange={(v) => { setQuoted(v); setDirty(true); }} />
              <Btn sm onClick={() => { setQuoted(String(Math.round(Number(t.computed_price || 0) * 100) / 100)); setDirty(true); }}>Use computed</Btn>
            </div>
            <div className="ws-small ws-muted" style={{ marginTop: 6 }}>Defaults to what the ERP computed. Recalculate to see the margin at a new price.</div>
            {Number(t.quoted_price) > 0 && t.below_floor ? <div className="ws-mt-s"><Note tone="warn">Below the margin floor: a Costing Manager must approve it before it can be submitted.</Note></div> : null}
          </div>
        )}
        {!locked && (
          <div className="ws-card" style={{ padding: 14 }}>
            <div className="ws-stack" style={{ gap: 8 }}>
              <Btn sm onClick={() => void run("preview")} disabled={busy !== ""}><RefreshCw size={14} /> Recalculate</Btn>
              <Btn sm kind="dark" busy={busy === "save"} onClick={() => void run("save")} disabled={busy !== ""}>Save draft</Btn>
              <Btn sm kind="primary" busy={busy === "submit"} onClick={() => void run("submit")} disabled={busy !== ""}><Check size={14} /> Save &amp; submit</Btn>
              {onShowAll && <Btn sm kind="plain" onClick={onShowAll}><Calculator size={14} /> The detailed sheet</Btn>}
              {cs.url && <Btn sm kind="plain" onClick={() => window.open(cs.url, "_blank", "noopener")}><ExternalLink size={14} /> Open in the ERP</Btn>}
            </div>
          </div>
        )}
        {msgs.length > 0 && <Note>{msgs.map((m, i) => <div key={i} dangerouslySetInnerHTML={{ __html: m.replace(/<(?!br\s*\/?)[^>]+>/g, "") }} />)}</Note>}
      </div>
    </div>
  );
}
