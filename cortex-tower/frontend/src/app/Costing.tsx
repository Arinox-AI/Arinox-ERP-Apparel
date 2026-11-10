import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Calculator, ChevronRight, Lock, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { Badge, Btn, Card, Head, Loading, Note, call, money, num, useCall, useToast, when } from "./kit";
import type { R } from "./kit";
import { CostSheetTab } from "./CostSheetTab";

/* ───────────────────────── the Costing page ─────────────────────────
   One extra page: the factory's costing sheet (APPAREL_COSTING_DETAILED_REVISED, sheet "DETAILED COSTING")
   per style — what every line costs, the price editable, a line addable — and one button that puts all of it
   into the ERP Cost Sheet.

   The arithmetic is NOT here: `costing_sheet.compute` on the server adds it up, through `deal_cost_sheet_calc`,
   so what the page shows is what a save stores. */

export function Costing({ go, dealId, styleKey }: { go: (p: string) => void; dealId?: string; styleKey?: string }) {
  if (dealId && styleKey) return <Sheet go={go} dealId={Number(dealId)} styleKey={styleKey} />;
  return <SheetList go={go} />;
}

function statusOf(r: R): { label: string; tone: any } {
  if (r.erp_cost_status === "submitted") return { label: "Costed in the ERP", tone: "ok" };
  if (r.transferred_at) return { label: "Transferred", tone: "teal" };
  if (r.sheet_id) return { label: "Draft", tone: "warn" };
  return { label: "Not started", tone: undefined };
}

function SheetList({ go }: { go: (p: string) => void }) {
  const { data, error, loading, reload } = useCall("cost_sheet_list");
  const [q, setQ] = useState("");
  const rows: R[] = useMemo(() => {
    const all: R[] = data?.sheets || [];
    const needle = q.trim().toLowerCase();
    return all.filter((r) => !needle || [r.style_no, r.style_name, r.customer_name, r.deal_title].join(" ").toLowerCase().includes(needle));
  }, [data, q]);

  return (
    <div className="ws-page">
      <Head title="Costing" sub="The costing sheet of every style: what each line costs, the price as you want it, one click into the ERP."
        acts={<div className="ws-row">
          <input className="ws-input" style={{ width: 220 }} placeholder="Style, buyer, deal…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a style" />
          <Btn sm icon title="Refresh" onClick={() => reload(true)}><RefreshCw size={14} /></Btn>
        </div>} />
      {error ? <Note tone="bad">{error}</Note> : loading && !data ? <Loading rows={5} /> : (
        <Card title={`${rows.length} style${rows.length === 1 ? "" : "s"}`} sub={`${rows.filter((r) => r.sheet_id).length} with a sheet started`} flush>
          {!rows.length ? <div style={{ padding: 18 }}><Note>No style yet. A style shows up here as soon as its inquiry is in the ERP.</Note></div> : (
            <div className="ws-table-wrap">
              <table className="ws-table">
                <thead><tr>
                  <th>Style</th><th>Buyer</th><th className="num">Qty</th><th className="num">FOB / pc</th>
                  <th className="num">Order value</th><th>Status</th><th>Updated</th><th />
                </tr></thead>
                <tbody>{rows.map((r) => {
                  const st = statusOf(r);
                  return (
                    <tr key={`${r.deal_id}-${r.style_key}`} style={{ cursor: "pointer" }}
                      onClick={() => go(`costing/${r.deal_id}/${encodeURIComponent(r.style_key)}`)}>
                      <td><b>{r.style_no}</b><div className="ws-small ws-muted">{r.style_name || r.deal_title}</div></td>
                      <td>{r.customer_name || "—"}<div className="ws-small ws-muted">Deal #{r.deal_id}</div></td>
                      <td className="num">{num(r.order_qty || r.qty)}</td>
                      <td className="num">{r.fob_usd ? money(r.fob_usd, r.currency, 3) : "—"}</td>
                      <td className="num">{r.order_value ? money(r.order_value, r.currency, 0) : "—"}</td>
                      <td><Badge tone={st.tone}>{st.label}</Badge></td>
                      <td className="ws-small ws-muted">{r.updated_at ? when(r.updated_at) : "—"}</td>
                      <td className="ws-right"><ChevronRight size={15} color="var(--ws-faint)" /></td>
                    </tr>);
                })}</tbody>
              </table>
            </div>)}
        </Card>)}
    </div>
  );
}

/* ───────────────────────── one style's sheet ───────────────────────── */

function Sheet({ go, dealId, styleKey }: { go: (p: string) => void; dealId: number; styleKey: string }) {
  const toast = useToast();
  const [sheet, setSheet] = useState<R | null>(null);
  const [rows, setRows] = useState<R[]>([]);
  const [totals, setTotals] = useState<R>({});
  const [deal, setDeal] = useState<R | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [dirty, setDirty] = useState(false);
  const [missing, setMissing] = useState<string[]>([]);
  /* two tabs, one page: the ERP's own cost sheet (what the ERP holds and will submit) and the detailed sheet (every line
     of the workbook). Both are the same costing seen from the two sides that matter - the factory's page and the ERP's. */
  const [tab, setTab] = useState<"erp" | "all">("erp");
  const tick = useRef(0);

  const load = useCallback(async () => {
    const r = await call("deal_cost_sheet", { deal_id: dealId, style_key: styleKey });
    if (!r.ok) { setErr(r.error || "Could not open the costing sheet."); return; }
    setSheet(r.sheet); setRows((r.lines || []).map((x: R) => ({ ...x }))); setTotals(r.totals || {}); setDeal(r.deal);
    setDirty(false);
  }, [dealId, styleKey]);
  useEffect(() => { void load(); }, [load]);

  const header = useMemo(() => {
    if (!sheet) return {};
    const k = ["order_qty", "pcs_per_carton", "profit_pct", "currency", "fob_port", "version", "note", "buyer", "season",
      "factory", "costing_date", "vnd_per_usd", "style_name", "style_no"] as const;
    const out: R = {};
    for (const key of k) out[key] = sheet[key];
    return out;
  }, [sheet]);

  /* live: the server adds the sheet up as it is on screen, so the FOB moves with the rate (no writes) */
  const recalc = useCallback(async () => {
    const r = await call("deal_cost_sheet_calc", { deal_id: dealId, style_key: styleKey, header, lines: rows });
    if (r.ok && r.totals) setTotals(r.totals);
  }, [dealId, styleKey, header, rows]);
  useEffect(() => {
    if (!sheet) return;
    const my = ++tick.current;
    const t = window.setTimeout(() => { if (my === tick.current) void recalc(); }, 350);
    return () => window.clearTimeout(t);
  }, [sheet, recalc]);

  const setHead = (k: string, v: any) => { setDirty(true); setSheet((s) => s && { ...s, [k]: v }); };
  const setRow = (i: number, k: string, v: any) => { setDirty(true); setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r))); };
  const numOrNull = (v: string) => (v === "" ? null : Number(v));

  const save = async (quiet = false) => {
    setBusy("save"); setErr("");
    const r = await call("deal_cost_sheet_save", { deal_id: dealId, style_key: styleKey, header, lines: rows });
    setBusy("");
    if (!r.ok) { setErr(r.error || "The sheet was not saved."); return null; }
    setSheet(r.sheet); setRows((r.lines || []).map((x: R) => ({ ...x }))); setTotals(r.totals || {}); setDirty(false);
    if (r.deal) setDeal(r.deal);
    if (!quiet) toast(`Saved. FOB ${money(r.totals?.fob_usd, r.sheet?.currency || "USD", 3)} per pc.`);
    return r;
  };

  /* the button: what each item costs, put on the BOM items that came in with the inquiry */
  const applyPrices = async () => {
    setBusy("bom"); setErr(""); setMissing([]);
    if (dirty) { const ok = await save(true); if (!ok) { setBusy(""); return; } }
    const r = await call("deal_cost_apply_prices", { deal_id: dealId, style_key: styleKey });
    setBusy("");
    if (!r.ok) { setErr(r.error || "The ERP refused the prices."); return; }
    setMissing(r.missing || []);
    if (!r.updated) {
      toast(r.priced ? `Nothing to change: ${r.priced} of ${r.items} BOM item(s) already carry these prices.`
        : "No BOM item has a price yet - fill the rates on the sheet first.", "bad");
      return;
    }
    toast(`${r.updated} BOM item(s) priced in the ERP (${r.priced} of ${r.items} items have a price).`);
  };

  const addLine = (kind: string) => {
    setDirty(true);
    setRows((rs) => {
      const last = rs.map((r, i) => [r, i] as [R, number]).filter(([r]) => r.kind === kind).pop();
      const at = last ? last[1] + 1 : rs.length;
      const blank: R = kind === "material"
        ? { kind, tpl: null, label: "", material_type: "Other", uom: "PCS", usage: null, wastage_pct: null, rate: null, apply: true, rule: null }
        : kind === "processing"
          ? { kind, tpl: null, label: "", cost_head: "", rate: null, apply: true }
          : { kind, tpl: null, label: "", cost_head: "", share: 0, apply: true };
      return [...rs.slice(0, at), blank, ...rs.slice(at)];
    });
  };

  if (err && !sheet) return <div className="ws-page"><Note tone="bad">{err}</Note><div className="ws-mt"><Btn onClick={() => go("costing")}>Back to costing</Btn></div></div>;
  if (!sheet) return <div className="ws-page"><Loading rows={6} /></div>;

  const style = (deal?.styles || []).find((s: R) => s.key === styleKey) || {};
  const ccy = sheet.currency || "USD";
  const locked = style.cost_status === "submitted";
  const profitRow = rows.map((r, i) => [r, i] as [R, number]).find(([r]) => String(r.cost_head || "").toLowerCase() === "profit");
  const costOf = (r: R) => { const t = (totals.rows || []).find((x: R) => (r.id && x.id === r.id) || (!r.id && x.label === r.label && x.kind === r.kind)); return t ? t.cost_per_pc : null; };
  const effUsage = (r: R) => { const t = (totals.rows || []).find((x: R) => (r.id && x.id === r.id) || (!r.id && x.label === r.label && x.kind === r.kind)); return t ? t.usage_effective : null; };
  const group = (kind: string) => rows.map((r, i) => [r, i] as [R, number]).filter(([r]) => r.kind === kind && r !== profitRow?.[0]);
  const fobLabel = `FOB ${sheet.fob_port || ""} PRICE PER PC`.replace(/\s+/g, " ");

  return (
    <div className="ws-page">
      <div className="ws-row" style={{ marginBottom: 10 }}>
        <Btn kind="plain" sm onClick={() => go("costing")}><ArrowLeft size={14} /> Costing</Btn>
        <Btn kind="plain" sm onClick={() => go(`deals/${dealId}`)}>The deal</Btn>
        <span style={{ marginLeft: "auto" }} className="ws-small ws-muted">
          {locked ? "submitted in the ERP - read only here" : dirty ? "unsaved" : sheet.transferred_at ? `transferred ${when(sheet.transferred_at)}` : "not transferred yet"}
        </span>
      </div>

      <Head title={`Costing · ${sheet.style_no || style.style_no || "style"}`}
        sub={[sheet.style_name || style.style_name, deal?.customer_name || deal?.customer, `${num(sheet.order_qty || style.qty)} pcs`].filter(Boolean).join(" · ")}
        acts={tab === "all" ? <div className="ws-row" style={{ flexWrap: "wrap" }}>
          <Btn sm busy={busy === "save"} disabled={locked} onClick={() => void save()}><Calculator size={14} /> Save</Btn>
          <Btn sm kind="primary" busy={busy === "bom"} disabled={locked} onClick={() => void applyPrices()}
            title="Put the price of each item on the BOM items that came in with the inquiry (a draft in the ERP - change it there if you need to)">
            <Upload size={14} /> Apply prices to the BOM</Btn>
        </div> : undefined} />

      <div className="ws-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "erp"} className={`ws-tab${tab === "erp" ? " is-on" : ""}`} onClick={() => setTab("erp")}>Cost sheet</button>
        <button role="tab" aria-selected={tab === "all"} className={`ws-tab${tab === "all" ? " is-on" : ""}`} onClick={() => setTab("all")}>Everything</button>
      </div>

      {err && <div style={{ marginBottom: 10 }}><Note tone="bad">{err}</Note></div>}
      {locked && tab === "all" && <div style={{ marginBottom: 10 }}><Note tone="ok">This costing is submitted in the ERP, so the sheet is read-only here.</Note></div>}

      {tab === "erp" && (style.cost_sheet && deal
        ? <CostSheetTab deal={deal} styleKey={styleKey} onShowAll={() => setTab("all")} onSaved={() => void load()} />
        : <Card title="Cost sheet"><Note>Send the inquiry to the ERP first (step 1 of the deal). It makes the Tech Pack, and the
          ERP's Cost Sheet is made from its Buyer BOM. The detailed sheet on the other tab is here already.</Note>
          <div className="ws-mt-s"><Btn sm onClick={() => setTab("all")}>The detailed sheet</Btn></div></Card>)}

      {tab === "all" && <div className="cs-sheet">
        <div className="cs-title"><b>APPAREL COSTING DETAILED</b><span>(PROGRAMS &gt; 5 K)</span></div>

        <div className="cs-head">
          <label className="cs-field"><span className="cs-lbl">STYLE NAME</span>
            <input className="cs-in" value={sheet.style_name || ""} onChange={(e) => setHead("style_name", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">BUYER</span>
            <input className="cs-in" value={sheet.buyer || ""} onChange={(e) => setHead("buyer", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">STYLE NO.</span>
            <input className="cs-in" value={sheet.style_no || ""} onChange={(e) => setHead("style_no", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">SEASON</span>
            <input className="cs-in" value={sheet.season || ""} onChange={(e) => setHead("season", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">ORDER QTY (PCS)</span>
            <input className="cs-in cs-num" type="number" value={sheet.order_qty ?? ""} onChange={(e) => setHead("order_qty", numOrNull(e.target.value))} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">FACTORY</span>
            <input className="cs-in" value={sheet.factory || ""} onChange={(e) => setHead("factory", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">FOB PORT</span>
            <input className="cs-in" value={sheet.fob_port || ""} onChange={(e) => setHead("fob_port", e.target.value)} disabled={locked} placeholder="HCM" /></label>
          <label className="cs-field"><span className="cs-lbl">COSTING DATE</span>
            <input className="cs-in" type="date" value={String(sheet.costing_date || "").slice(0, 10)} onChange={(e) => setHead("costing_date", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">CURRENCY</span>
            <input className="cs-in" value={sheet.currency || "USD"} onChange={(e) => setHead("currency", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">VND PER USD</span>
            <input className="cs-in cs-num" type="number" value={sheet.vnd_per_usd ?? ""} onChange={(e) => setHead("vnd_per_usd", numOrNull(e.target.value))} disabled={locked} placeholder="25000" /></label>
          <label className="cs-field"><span className="cs-lbl">COSTING VERSION</span>
            <input className="cs-in" value={sheet.version || ""} onChange={(e) => setHead("version", e.target.value)} disabled={locked} /></label>
          <label className="cs-field"><span className="cs-lbl">PCS PER CARTON</span>
            <input className="cs-in cs-num" type="number" value={sheet.pcs_per_carton ?? ""} onChange={(e) => setHead("pcs_per_carton", numOrNull(e.target.value))} disabled={locked} placeholder="40" /></label>
        </div>

        <div className="cs-group cs-scroll">
          <div className="cs-ghead"><b>A · RAW MATERIALS</b><span>usage / pc × (1 + wastage) × rate</span></div>
          <table className="cs-table">
            <thead><tr>
              <th style={{ width: 34 }} className="cs-num">SNO</th><th>RAW MATERIALS</th>
              <th className="cs-num" style={{ width: 96 }}>USAGE / PC</th><th style={{ width: 62 }}>UNIT</th>
              <th className="cs-num" style={{ width: 88 }}>WASTAGE %</th><th className="cs-num" style={{ width: 100 }}>RATE ({ccy})</th>
              <th className="cs-num" style={{ width: 96 }}>COST / PC</th><th style={{ width: 28 }} />
            </tr></thead>
            <tbody>
              {group("material").map(([r, i], n) => (
                <tr key={r.id || `m${i}`} style={{ opacity: r.apply ? 1 : 0.5 }}>
                  <td className="cs-num cs-small">{n + 1}</td>
                  <td>
                    <input className="cs-in" value={r.label} onChange={(e) => setRow(i, "label", e.target.value)} disabled={locked} placeholder="material" />
                    {(r.item_desc || r.item_code) && <div className="cs-item" title="the BOM item this price is for">
                      {r.item_code ? `${r.item_code} · ` : ""}{r.item_desc || ""}
                    </div>}
                  </td>
                  <td className="cs-num">
                    {r.rule
                      ? <span title={r.rule === "per_carton" ? "1 / pcs per carton" : "the fabric metres including wastage"}>{num(effUsage(r), 4)} <Lock size={9} /></span>
                      : <input className="cs-in cs-num" type="number" value={r.usage ?? ""} onChange={(e) => setRow(i, "usage", numOrNull(e.target.value))} disabled={locked} />}
                  </td>
                  <td><input className="cs-in" value={r.uom || ""} onChange={(e) => setRow(i, "uom", e.target.value)} disabled={locked} /></td>
                  <td className="cs-num"><input className="cs-in cs-num" type="number" step="0.5" value={r.wastage_pct == null ? "" : Number(r.wastage_pct) * 100}
                    onChange={(e) => setRow(i, "wastage_pct", e.target.value === "" ? null : Number(e.target.value) / 100)} disabled={locked} /></td>
                  <td className="cs-num"><input className="cs-in cs-num" type="number" step="0.001" value={r.rate ?? ""} onChange={(e) => setRow(i, "rate", numOrNull(e.target.value))} disabled={locked} /></td>
                  <td className="cs-num cs-cost">{num(costOf(r), 4)}</td>
                  <td>{!locked && <button className="cs-del" title="Remove this line" onClick={() => { setDirty(true); setRows((rs) => rs.filter((_, j) => j !== i)); }}><Trash2 size={12} /></button>}</td>
                </tr>))}
              <tr className="cs-total"><td colSpan={6}>TOTAL COST OF RAW MATERIALS</td><td className="cs-num cs-cost">{num(totals.raw_material, 4)}</td><td /></tr>
            </tbody>
          </table>
          {!locked && <button className="cs-add" onClick={() => addLine("material")}><Plus size={12} /> add a raw material</button>}
          {missing.length > 0 && <div className="ws-mt-s"><Note tone="warn">
            No price yet for {missing.length} BOM item{missing.length === 1 ? "" : "s"}: {missing.join(", ")}. Give that line a rate and press the button again.
          </Note></div>}
        </div>

        <div className="cs-group cs-scroll">
          <div className="cs-ghead"><b>B · PROCESSING CHARGES</b><span>APPLY 1/0 × rate per piece</span></div>
          <table className="cs-table">
            <thead><tr>
              <th style={{ width: 34 }} className="cs-num">SNO</th><th>PROCESSING CHARGES</th>
              <th style={{ width: 90 }} className="cs-num">APPLY (1/0)</th><th className="cs-num" style={{ width: 110 }}>RATE ({ccy})</th>
              <th className="cs-num" style={{ width: 96 }}>COST / PC</th><th style={{ width: 28 }} />
            </tr></thead>
            <tbody>
              {group("processing").map(([r, i], n) => (
                <tr key={r.id || `p${i}`} style={{ opacity: r.apply ? 1 : 0.55 }}>
                  <td className="cs-num cs-small">{n + 1}</td>
                  <td><input className="cs-in" value={r.label} onChange={(e) => setRow(i, "label", e.target.value)} disabled={locked} placeholder="charge" /></td>
                  <td className="cs-num"><input type="checkbox" checked={!!r.apply} onChange={(e) => setRow(i, "apply", e.target.checked)} disabled={locked} aria-label={`${r.label} applies`} /></td>
                  <td className="cs-num"><input className="cs-in cs-num" type="number" step="0.01" value={r.rate ?? ""} onChange={(e) => setRow(i, "rate", numOrNull(e.target.value))} disabled={locked} /></td>
                  <td className="cs-num cs-cost">{num(costOf(r), 4)}</td>
                  <td>{!locked && <button className="cs-del" title="Remove this line" onClick={() => { setDirty(true); setRows((rs) => rs.filter((_, j) => j !== i)); }}><Trash2 size={12} /></button>}</td>
                </tr>))}
              <tr className="cs-total"><td colSpan={4}>TOTAL COST OF PROCESS CHARGES</td><td className="cs-num cs-cost">{num(totals.processing, 4)}</td><td /></tr>
              <tr className="cs-grand"><td colSpan={4}>TOTAL COST OF THE PRODUCT</td><td className="cs-num">{num(totals.product_cost, 4)}</td><td /></tr>
            </tbody>
          </table>
          {!locked && <button className="cs-add" onClick={() => addLine("processing")}><Plus size={12} /> add a processing charge</button>}
        </div>

        <div className="cs-group cs-scroll">
          <div className="cs-ghead"><b>C · OTHER EXPENSES (% OF PRODUCT COST)</b><span>% of the product cost</span></div>
          <table className="cs-table">
            <thead><tr>
              <th style={{ width: 34 }} className="cs-num">SNO</th><th>OTHER EXPENSES</th>
              <th className="cs-num" style={{ width: 96 }}>%</th><th className="cs-num" style={{ width: 96 }}>COST / PC</th><th style={{ width: 28 }} />
            </tr></thead>
            <tbody>
              {group("expense").map(([r, i], n) => (
                <tr key={r.id || `e${i}`} style={{ opacity: r.apply ? 1 : 0.55 }}>
                  <td className="cs-num cs-small">{n + 1}</td>
                  <td><input className="cs-in" value={r.label} onChange={(e) => setRow(i, "label", e.target.value)} disabled={locked} placeholder="expense" /></td>
                  <td className="cs-num"><input className="cs-in cs-num" type="number" step="0.5" value={r.share == null ? "" : Number(r.share) * 100}
                    onChange={(e) => setRow(i, "share", e.target.value === "" ? null : Number(e.target.value) / 100)} disabled={locked} /></td>
                  <td className="cs-num cs-cost">{num(costOf(r), 4)}</td>
                  <td>{!locked && <button className="cs-del" title="Remove this line" onClick={() => { setDirty(true); setRows((rs) => rs.filter((_, j) => j !== i)); }}><Trash2 size={12} /></button>}</td>
                </tr>))}
              <tr className="cs-total"><td colSpan={3}>TOTAL COST OF OTHER EXPENSES</td><td className="cs-num cs-cost">{num(totals.other_expenses, 4)}</td><td /></tr>
              <tr className="cs-grand"><td colSpan={3}>TOTAL FOB COST (BEFORE PROFIT)</td><td className="cs-num">{num(totals.fob_before_profit, 4)}</td><td /></tr>
              {profitRow && (
                <tr className="cs-grand">
                  <td /><td><input className="cs-in" value={profitRow[0].label} onChange={(e) => setRow(profitRow[1], "label", e.target.value)} disabled={locked} /></td>
                  <td className="cs-num"><input className="cs-in cs-num" type="number" step="0.5" value={profitRow[0].share == null ? "" : Number(profitRow[0].share) * 100}
                    onChange={(e) => { setRow(profitRow[1], "share", e.target.value === "" ? null : Number(e.target.value) / 100); setHead("profit_pct", e.target.value === "" ? null : Number(e.target.value) / 100); }} disabled={locked} /></td>
                  <td className="cs-num cs-cost">{num(totals.profit, 4)}</td><td />
                </tr>)}
            </tbody>
          </table>
          {!locked && <button className="cs-add" onClick={() => addLine("expense")}><Plus size={12} /> add an expense</button>}
        </div>

        <div className="cs-out">
          <div><span>{fobLabel} (USD)</span><b>{money(totals.fob_usd, "", 4)}</b></div>
          <div><span>{fobLabel} (VND)</span><b>{totals.fob_vnd ? num(totals.fob_vnd, 0) : "—"}</b></div>
          <div><span>TOTAL ORDER VALUE (USD)</span><b>{money(totals.order_value, "", 0)}</b></div>
        </div>
      </div>}
    </div>
  );
}
