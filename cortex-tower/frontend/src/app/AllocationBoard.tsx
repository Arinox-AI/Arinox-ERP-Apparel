import { useEffect, useMemo, useState } from "react";
import { ExternalLink, Plus, Sparkles, Trash2 } from "lucide-react";
import { Badge, Btn, Card, Empty, Input, Loading, Modal, Note, Select, call, day, num, useCall, useToast } from "./kit";
import type { R } from "./kit";

/* Step 2 of the Order page: where to produce (ORDER_TO_SHIP_PLAN section 5, D3). The tower suggests, the planner approves:
   the draft from `order_allocation_get` is pre-filled and fully editable; "Check with the ERP" runs the ERP's own validation
   (`order_allocation_save` with preview); saving always shows the preview first and is confirmed by the planner. */

type Row = { style_item: string; colour: string; qty: number | string; factory: string; line: string; pcd: string; sewing_start: string; sewing_end: string; ship_to?: string; buyer_po?: string; reason?: string };

const blank = (g: R): Row => ({ style_item: g.style_item, colour: g.colour, qty: 0, factory: "", line: "", pcd: "", sewing_start: "", sewing_end: "", ship_to: g.ship_to || "", buyer_po: g.buyer_po || "" });
const same = (a: Row[], b: Row[]) => JSON.stringify(a.map((r) => [r.style_item, r.colour, +r.qty, r.factory, r.line, r.pcd, r.sewing_start, r.sewing_end])) === JSON.stringify(b.map((r) => [r.style_item, r.colour, +r.qty, r.factory, r.line, r.pcd, r.sewing_start, r.sewing_end]));

export function AllocationBoard({ so, onSaved }: { so: string; onSaved: () => void }) {
  const toast = useToast();
  const r = useCall("order_allocation_get", { sales_order: so }, []);
  const d: R | undefined = r.data || undefined;
  const [rows, setRows] = useState<Row[] | null>(null);
  const [origin, setOrigin] = useState<"suggestion" | "saved" | "empty">("empty");
  const [untouched, setUntouched] = useState<Row[]>([]);
  const [why, setWhy] = useState<number | null>(null);
  const [check, setCheck] = useState<R | null>(null);
  const [confirm, setConfirm] = useState<R | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!d) return;
    const saved: Row[] = (d.current?.lines || []).map((l: R) => ({ ...l, qty: l.qty }));
    const sug: Row[] = d.suggestion?.lines || [];
    if (saved.length) { setRows(saved); setOrigin("saved"); setUntouched([]); }
    else if (sug.length) { setRows(sug); setOrigin("suggestion"); setUntouched(sug); }
    else { setRows([]); setOrigin("empty"); setUntouched([]); }
    setCheck(null);
  }, [d]);

  const lines: R[] = d?.order_lines || [];
  const factories: R[] = d?.factories || [];
  const lineNames = (f: string) => (factories.find((x) => x.name === f)?.lines || []).map((l: R) => l.name);
  const patch = (i: number, p: Partial<Row>) => { setRows((rs) => (rs || []).map((x, k) => (k === i ? { ...x, ...p } : x))); setCheck(null); };
  const totals = useMemo(() => {
    const t: Record<string, number> = {};
    for (const x of rows || []) { const k = x.style_item + "|" + x.colour; t[k] = (t[k] || 0) + (Number(x.qty) || 0); }
    return t;
  }, [rows]);
  if (r.loading && !d) return <Card title="Where to produce"><Loading rows={3} /></Card>;
  if (!d) return <Card title="Where to produce"><Note tone="bad">{r.error || "The allocation could not be read."}</Note></Card>;

  const sug: R = d.suggestion || { lines: [], shortfalls: [], unknown_lines: [] };
  const payload = () => {
    const mine = (rows || []).filter((x) => Number(x.qty) > 0);
    const asSuggested = origin === "suggestion" && same(mine, untouched);
    return { sales_order: so, lines: mine, planned_by: asSuggested ? "AI Agent" : "Manual", agent_notes: sug.notes || "" };
  };
  const run = async (kind: "check" | "save") => {
    setBusy(kind);
    const res = await call("order_allocation_save", { ...payload(), preview: kind === "check" || kind === "save" });
    setBusy("");
    if (kind === "check") { setCheck(res); return; }
    if (!res.ok) { setCheck(res); toast(res.error || "The ERP refused it.", "bad"); return; }
    setConfirm(res);
  };
  const doSave = async () => {
    setBusy("commit");
    const res = await call("order_allocation_save", { ...payload(), preview: false });
    setBusy("");
    if (!res.ok) { toast(res.error || "The ERP refused it.", "bad"); setConfirm(null); setCheck(res); return; }
    setConfirm(null); toast(`Allocation ${res.name} saved.`); onSaved(); void r.reload(true);
  };
  const resuggest = () => { setRows(sug.lines || []); setOrigin("suggestion"); setUntouched(sug.lines || []); setCheck(null); };
  const weeks: string[] = d.load_strip?.weeks || [];
  const strip: Record<string, number[]> = d.load_strip?.load || {};
  const maxLoad = Math.max(1, ...Object.values(strip).flat());
  const nothing = !(rows || []).length;

  return (
    <>
      {(d.setup || []).length > 0 && (
        <Card title="Set up first" sub="The suggester will not place work where it cannot know the capacity, and it never invents a factory or a line.">
          <div className="ws-stack">{d.setup.map((s: R, i: number) => (
            <Note key={i} tone="warn">{s.text}{s.url && <> <Btn kind="plain" sm onClick={() => window.open(s.url, "_blank", "noopener")}><ExternalLink size={12} /> {s.label}</Btn></>}</Note>))}</div>
        </Card>)}

      <Card title="Where to produce" sub={origin === "saved" ? "The saved allocation. Edit it, or ask for a new suggestion." : origin === "suggestion" ? "Suggested by the tower from line capacity and what is already booked. Check it, change anything, then save." : "Nothing is allocated yet."}
        right={<><Btn sm onClick={resuggest}><Sparkles size={13} /> Suggest again</Btn>
          <Btn sm onClick={() => setRows([...(rows || []), blank(lines[0] || {})])}><Plus size={13} /> Add a row</Btn></>}>
        {nothing && lines.length > 0 && <div className="ws-mb"><Empty title="No rows" text="Use Suggest again, or add a row for each style and colour." /></div>}
        <div className="ws-table-wrap"><table className="ws-table ws-table--edit" aria-label="Allocation" style={{ minWidth: 980 }}>
          <thead><tr><th>Style / colour</th><th className="num">Qty</th><th>Factory</th><th>Line</th><th>PCD</th><th>Sewing start</th><th>Sewing end</th><th /></tr></thead>
          <tbody>{(rows || []).map((x, i) => (
            <tr key={i}>
              <td><Select sm value={x.style_item + "|" + x.colour} onChange={(v) => { const [s, c] = v.split("|"); patch(i, { style_item: s, colour: c }); }}
                options={lines.map((g) => ({ v: g.style_item + "|" + g.colour, l: `${g.style_item} / ${g.colour}` }))} /></td>
              <td className="num" style={{ width: 90 }}><Input sm num type="number" value={x.qty} onChange={(v) => patch(i, { qty: v })} aria-label="Quantity" /></td>
              <td><Select sm value={x.factory} onChange={(v) => patch(i, { factory: v, line: "" })} placeholder="Factory" options={factories.map((f) => f.name)} /></td>
              <td><Select sm value={x.line} onChange={(v) => patch(i, { line: v })} placeholder="Line" options={lineNames(x.factory)} /></td>
              <td><Input sm type="date" value={x.pcd} onChange={(v) => patch(i, { pcd: v })} aria-label="PCD" /></td>
              <td><Input sm type="date" value={x.sewing_start} onChange={(v) => patch(i, { sewing_start: v })} aria-label="Sewing start" /></td>
              <td><Input sm type="date" value={x.sewing_end} onChange={(v) => patch(i, { sewing_end: v })} aria-label="Sewing end" /></td>
              <td style={{ whiteSpace: "nowrap" }}>
                {x.reason && <Btn sm kind="plain" onClick={() => setWhy(why === i ? null : i)}>Why this?</Btn>}
                <Btn sm kind="plain" icon title="Remove the row" onClick={() => { setRows((rs) => (rs || []).filter((_, k) => k !== i)); setCheck(null); }}><Trash2 size={13} /></Btn>
              </td>
            </tr>))}</tbody></table></div>
        {why !== null && rows?.[why]?.reason && <div className="ws-mt"><Note>{rows[why].reason}</Note></div>}

        <div className="ws-mt ws-stack">
          {lines.map((g) => {
            const k = g.style_item + "|" + g.colour; const got = totals[k] || 0; const ok = got >= g.qty && got <= Math.floor(g.qty * (1 + (g.tolerance_pct || 0) / 100));
            return <div key={k} className="ws-row ws-small"><b>{g.style_item} / {g.colour}</b><span className="ws-muted">ordered {num(g.qty)}, ex-factory {day(g.ex_factory_date)}</span>
              <Badge tone={got === 0 ? undefined : ok ? "ok" : "warn"}>{num(got)} allocated</Badge></div>;
          })}
          {(sug.shortfalls || []).map((s: R, i: number) => <Note key={i} tone="bad"><b>{s.style_item} / {s.colour}</b> ({num(s.qty_short)} pcs) {s.reason}{s.earliest_ex_factory ? ` Earliest feasible ex-factory: ${day(s.earliest_ex_factory)}.` : ""}</Note>)}
          {(sug.unknown_lines || []).length > 0 && <Note tone="warn">{sug.unknown_lines.join(" ")}</Note>}
          {check && (check.ok ? <Note tone="ok">The ERP accepts this allocation as it is. Nothing was saved.</Note> : <Note tone="bad">The ERP refuses it: {check.error}</Note>)}
        </div>
        <div className="ws-row ws-mt">
          <Btn busy={busy === "check"} disabled={nothing} onClick={() => run("check")}>Check with the ERP</Btn>
          <Btn kind="primary" busy={busy === "save"} disabled={nothing} onClick={() => run("save")}>Save the allocation</Btn>
          <span className="ws-small ws-muted">{origin === "suggestion" ? "Saved as planned by the tower if you change nothing; as manual if you do." : "Saved as a manual plan."}</span>
        </div>
      </Card>

      {weeks.length > 0 && Object.keys(strip).length > 0 && (
        <Card title="Load on each line" sub="Pieces already booked by other orders in the next eight weeks." flush>
          <div className="ws-table-wrap"><table className="ws-table" aria-label="Line load">
            <thead><tr><th>Line</th>{weeks.map((w) => <th key={w} className="num">{day(w).replace(/, \d{4}$/, "")}</th>)}</tr></thead>
            <tbody>{Object.entries(strip).map(([ln, vals]) => (
              <tr key={ln}><td><b className="ws-small">{ln}</b></td>{vals.map((v, i) => (
                <td key={i} className="num ws-small" style={{ background: v ? `rgba(37,99,235,${0.08 + 0.4 * (v / maxLoad)})` : undefined }}>{v ? num(v) : "·"}</td>))}</tr>))}</tbody></table></div>
        </Card>)}

      {confirm && (
        <Modal title="Save this allocation?" sub="This is what the ERP will do. Nothing has been written yet." onClose={() => setConfirm(null)}
          foot={<><Btn onClick={() => setConfirm(null)}>Cancel</Btn><Btn kind="primary" busy={busy === "commit"} onClick={doSave}>Confirm and save</Btn></>}>
          <dl className="ws-kv"><dt>Order</dt><dd>{so}</dd><dt>Rows</dt><dd>{(payload().lines || []).length}</dd><dt>Planned by</dt><dd>{payload().planned_by === "AI Agent" ? "The tower's suggestion, unchanged" : "You (manual)"}</dd>
            <dt>Pieces</dt><dd>{num(Object.values(totals).reduce((a, b) => a + b, 0))}</dd></dl>
          {(confirm.preview?.operations || []).map((o: R, i: number) => <div key={i} className="ws-small ws-muted">{o.op} {o.doctype} {o.name}</div>)}
          {(confirm.preview?.warnings || []).map((w: string, i: number) => <Note key={i} tone="warn">{w}</Note>)}
        </Modal>)}
    </>
  );
}
