import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, RefreshCw, Search } from "lucide-react";
import { call, fmtVal, slugTitle } from "../api";
import type { R } from "../api";
import { Btn, Cell, Empty, Foot, List, ListSkel, Note, Pill, Section, Seg, Sheet, Switch, Title, useCx } from "../ui";

export function tone(s: any): "green" | "orange" | "red" | "blue" | undefined {
  const v = String(s || "").toLowerCase();
  if (!v) return undefined;
  if (/(approved|accepted|complete|done|closed|paid|shipped|delivered|submitted|on track|signed|passed|agreed)/.test(v)) return "green";
  if (/(late|reject|cancel|fail|overdue|blocked|lost|hold|at risk)/.test(v)) return "red";
  if (/(draft|open|pending|not started|under review|in progress|partly|resubmit|new)/.test(v)) return "orange";
  return "blue";
}
export const DS = ["Draft", "Submitted", "Cancelled"];

/** Show a field? Understands the simple depends_on forms; anything else is shown (never evaluated as code). */
export function visible(f: R, vals: R): boolean {
  const d: string | undefined = f.depends_on;
  if (!d) return true;
  const e = d.startsWith("eval:") ? d.slice(5).trim() : d.trim();
  let m = e.match(/^(!)?\s*doc\.(\w+)$/) || (d.startsWith("eval:") ? null : e.match(/^()(\w+)$/));
  if (m) { const t = !!vals[m[2]] && vals[m[2]] !== "0"; return m[1] ? !t : t; }
  m = e.match(/^doc\.(\w+)\s*(==|===|!=|!==)\s*(?:"([^"]*)"|'([^']*)'|(\d+))$/);
  if (m) { const cur = String(vals[m[1]] ?? ""); const want = m[3] ?? m[4] ?? m[5]; const eq = cur === want; return m[2].startsWith("!") ? !eq : eq; }
  return true;
}

const opts = (f: R): string[] => String(f.options || "").split("\n").filter(Boolean);

/* ── one field editor ──────────────────────────────────────────────────── */
function LinkInput({ f, value, onChange }: { f: R; value: any; onChange: (v: string) => void }) {
  const [q, setQ] = useState(String(value ?? ""));
  const [res, setRes] = useState<R[]>([]);
  const [open, setOpen] = useState(false);
  const t = useRef<number | null>(null);
  useEffect(() => { setQ(String(value ?? "")); }, [value]);
  const search = (txt: string) => {
    setQ(txt); setOpen(true);
    if (t.current) window.clearTimeout(t.current);
    t.current = window.setTimeout(async () => {
      const r = await call("cx_link_search", { doctype: f.options, txt });
      setRes(r.ok ? r.results : []);
    }, 250);
  };
  return (
    <div style={{ position: "relative" }}>
      <input className="cx-input" value={q} placeholder={`Search ${f.options}`} onChange={(e) => search(e.target.value)} onFocus={() => search(q)}
        onBlur={() => window.setTimeout(() => setOpen(false), 180)} autoComplete="off" />
      {open && res.length > 0 && <div className="cx-menu">{res.map((r) => <button key={r.value} type="button" onMouseDown={(e) => e.preventDefault()}
        onClick={() => { onChange(r.value); setQ(r.value); setOpen(false); }}>{r.value}{r.description ? <small>{r.description}</small> : null}</button>)}</div>}
    </div>
  );
}

export function FieldEditor({ f, value, onChange }: { f: R; value: any; onChange: (v: any) => void }) {
  const t = f.fieldtype;
  if (t === "Check") return <div className="cx-field cx-field--row"><label>{f.label}</label><Switch on={!!Number(value)} onChange={(b) => onChange(b ? 1 : 0)} label={f.label} /></div>;
  let input;
  if (t === "Select") input = <select className="cx-select" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>{opts(f).map((o) => <option key={o} value={o}>{o || "—"}</option>)}{!opts(f).includes("") && <option value="">—</option>}</select>;
  else if (t === "Link") input = <LinkInput f={f} value={value} onChange={onChange} />;
  else if (t === "Date") input = <input className="cx-input" type="date" value={String(value ?? "").slice(0, 10)} onChange={(e) => onChange(e.target.value || null)} />;
  else if (t === "Datetime") input = <input className="cx-input" type="datetime-local" value={String(value ?? "").replace(" ", "T").slice(0, 16)} onChange={(e) => onChange(e.target.value ? e.target.value.replace("T", " ") + ":00" : null)} />;
  else if (["Int", "Float", "Currency", "Percent", "Long Int"].includes(t)) input = <input className="cx-input" type="number" inputMode="decimal" step={t === "Int" ? 1 : "any"} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
  else if (["Small Text", "Text", "Long Text", "Text Editor", "Code", "JSON"].includes(t)) input = <textarea className="cx-textarea" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  else if (["Attach", "Attach Image"].includes(t)) input = <div className="cx-cell__sub">{value ? String(value) : "Files are attached from the ERP form for now."}</div>;
  else input = <input className="cx-input" type="text" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  return <div className="cx-field"><label>{f.label}{f.reqd ? <span className="cx-req">*</span> : null}</label>{input}</div>;
}

function ChildEditor({ f, rows, onChange }: { f: R; rows: R[]; onChange: (r: R[]) => void }) {
  const cols: R[] = (f.columns || []).filter((c: R) => !c.read_only && !["Attach", "Attach Image", "Table"].includes(c.fieldtype)).slice(0, 8);
  const set = (i: number, k: string, v: any) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <>
      <Section right={<Btn kind="plain" sm onClick={() => onChange([...rows, {}])}><Plus size={15} /> Add row</Btn>}>{f.label}</Section>
      {rows.length === 0 && <div className="cx-list"><Cell title={<span style={{ color: "var(--cx-label-2)" }}>No rows yet</span>} /></div>}
      {rows.map((r, i) => (
        <div className="cx-list" key={i} style={{ marginBottom: 12 }}>
          {cols.map((c) => <FieldEditor key={c.fieldname} f={c} value={r[c.fieldname]} onChange={(v) => set(i, c.fieldname, v)} />)}
          <div style={{ padding: "6px 10px 10px" }}><Btn kind="danger" sm onClick={() => onChange(rows.filter((_, j) => j !== i))}>Remove row {i + 1}</Btn></div>
        </div>
      ))}
    </>
  );
}

/* ── form (create / edit) ───────────────────────────────────────────────── */
export function FormSheet({ doctype, name, initial, onClose, onSaved }: { doctype: string; name?: string; initial?: R; onClose: () => void; onSaved: (doc: R) => void }) {
  const cx = useCx();
  const [meta, setMeta] = useState<R | null>(null);
  const [orig, setOrig] = useState<R>({});
  const [vals, setVals] = useState<R>({});
  const [err, setErr] = useState<string>("");
  const [more, setMore] = useState(false);
  useEffect(() => {
    let live = true;
    (async () => {
      const m = await call("cx_doc_meta", { doctype });
      if (!live) return;
      if (!m.ok) { setErr(m.error); return; }
      setMeta(m);
      if (name) {
        const d = await call("cx_doc_get", { doctype, name });
        if (!live) return;
        if (!d.ok) { setErr(d.error); return; }
        setOrig(d.doc); setVals(d.doc);
      } else {
        const base: R = { ...(initial || {}) };
        for (const f of m.fields) if (base[f.fieldname] === undefined && f.default && !["Table"].includes(f.fieldtype)) base[f.fieldname] = f.default === "Today" ? new Date().toISOString().slice(0, 10) : f.default;
        setVals(base);
      }
    })();
    return () => { live = false; };
  }, [doctype, name, initial]);

  const submitted = Number(orig.docstatus) === 1;
  const editable = useMemo(() => (meta?.fields || []).filter((f: R) => !f.read_only && !f.hidden && f.fieldtype !== "Table"
      && (!submitted || f.allow_on_submit)), [meta, submitted]);
  const tables = useMemo(() => (meta?.fields || []).filter((f: R) => f.fieldtype === "Table" && f.columns?.length && !submitted), [meta, submitted]);
  const main = editable.filter((f: R) => f.reqd || f.in_list_view);
  const rest = editable.filter((f: R) => !(f.reqd || f.in_list_view));
  const set = (k: string, v: any) => setVals((p) => ({ ...p, [k]: v }));

  const save = () => {
    const missing = editable.filter((f: R) => f.reqd && visible(f, vals) && (vals[f.fieldname] === undefined || vals[f.fieldname] === null || vals[f.fieldname] === "")).map((f: R) => f.label);
    if (missing.length) { setErr(`Please fill in: ${missing.join(", ")}`); return; }
    setErr("");
    const data: R = {};
    for (const f of [...editable, ...tables]) {
      const k = f.fieldname;
      if (name) { if (JSON.stringify(vals[k] ?? null) !== JSON.stringify(orig[k] ?? null)) data[k] = vals[k]; }
      else if (vals[k] !== undefined && vals[k] !== "" && vals[k] !== null) data[k] = vals[k];
    }
    if (name && Object.keys(data).length === 0) { setErr("Nothing has changed."); return; }
    cx.review({
      title: name ? `Save ${doctype}` : `Create ${doctype}`, sub: name, confirmLabel: name ? "Save" : "Create",
      run: (preview, extra) => call("cx_write", { op: name ? "save" : "insert", doctype, name: name || "", data, modified: orig.modified || "", preview, ...extra }),
      done: (r) => { onSaved(r.doc || {}); },
    });
  };

  return (
    <Sheet title={name ? `Edit ${name}` : `New ${doctype}`} sub={doctype} onClose={onClose} wide
      foot={meta ? <><Btn kind="gray" onClick={onClose}>Cancel</Btn><Btn onClick={save}>{name ? "Review & save" : "Review & create"}</Btn></> : undefined}>
      {!meta && !err && <ListSkel n={4} />}
      {err && <Note tone="bad">{err}</Note>}
      {meta && <>
        {submitted && <Note>This record is submitted. Only the fields the ERP allows after submission can be changed.</Note>}
        {!name && meta.numbered && <Foot>The document number is given automatically when you create it.</Foot>}
        <div className="cx-list" style={{ marginTop: 8 }}>{main.filter((f: R) => visible(f, vals)).map((f: R) => <FieldEditor key={f.fieldname} f={f} value={vals[f.fieldname]} onChange={(v) => set(f.fieldname, v)} />)}</div>
        {tables.filter((f: R) => visible(f, vals)).map((f: R) => <ChildEditor key={f.fieldname} f={f} rows={vals[f.fieldname] || []} onChange={(r) => set(f.fieldname, r)} />)}
        {rest.length > 0 && <>
          <Section right={<Btn kind="plain" sm onClick={() => setMore(!more)}>{more ? "Hide" : "Show"}</Btn>}>More details</Section>
          {more && <div className="cx-list">{rest.filter((f: R) => visible(f, vals)).map((f: R) => <FieldEditor key={f.fieldname} f={f} value={vals[f.fieldname]} onChange={(v) => set(f.fieldname, v)} />)}</div>}
        </>}
      </>}
    </Sheet>
  );
}

/* ── detail ─────────────────────────────────────────────────────────────── */
export function DocSheet({ doctype, name, onClose }: { doctype: string; name: string; onClose: () => void }) {
  const cx = useCx();
  const [meta, setMeta] = useState<R | null>(null);
  const [d, setD] = useState<R | null>(null);
  const [err, setErr] = useState("");
  const [edit, setEdit] = useState(false);
  const load = useCallback(async () => {
    const [m, g] = await Promise.all([call("cx_doc_meta", { doctype }), call("cx_doc_get", { doctype, name })]);
    if (!m.ok) setErr(m.error); else if (!g.ok) setErr(g.error); else { setMeta(m); setD(g); setErr(""); }
  }, [doctype, name]);
  useEffect(() => { void load(); }, [load, cx.tick]);

  const doc = d?.doc || {};
  const fields: R[] = (meta?.fields || []).filter((f: R) => !f.hidden && f.fieldtype !== "Table");
  const shown = fields.filter((f) => doc[f.fieldname] !== null && doc[f.fieldname] !== undefined && doc[f.fieldname] !== "" && !(f.fieldtype === "Check" && !doc[f.fieldname]));
  const tables: R[] = (meta?.fields || []).filter((f: R) => f.fieldtype === "Table" && Array.isArray(doc[f.fieldname]) && doc[f.fieldname].length);
  const ds = Number(doc.docstatus || 0);

  const act = (label: string, op: string, danger = false) => cx.review({
    title: label, sub: `${doctype} ${name}`, confirmLabel: label,
    run: (preview, extra) => call("cx_write", { op, doctype, name, modified: doc.modified || "", preview, ...extra }),
    done: () => { void load(); cx.refresh(); },
  });
  const script = (method: string) => cx.review({
    title: slugTitle(method.replace("arinox_" + doctype.toLowerCase().replace(/ /g, "_") + "_", "")), sub: `${doctype} ${name}`,
    run: (preview, extra) => call("cx_run_script", { method, doctype, name, params: { name, doc: JSON.stringify(doc) }, preview, ...extra }),
    done: (r) => {
      const res = r.result;
      if (res && typeof res === "object" && !Array.isArray(res) && res.doctype && !res.name) cx.newDoc(res.doctype, res);
      void load(); cx.refresh();
    },
  });

  if (edit) return <FormSheet doctype={doctype} name={name} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); void load(); cx.refresh(); }} />;
  const label = (f: R) => {
    const v = doc[f.fieldname];
    if (f.fieldtype === "Link" && f.options) return <button className="cx-btn cx-btn--plain cx-btn--sm" style={{ padding: 0, minHeight: 0, font: "inherit", textAlign: "left" }} onClick={() => cx.openDoc(f.options, String(v))}>{String(v)}</button>;
    if (f.fieldtype === "Check") return "Yes";
    return fmtVal(v);
  };
  return (
    <Sheet title={name} sub={<>{doctype} {meta?.is_submittable ? <Pill tone={ds === 1 ? "green" : ds === 2 ? "red" : undefined}>{DS[ds]}</Pill> : null} {doc.status ? <Pill tone={tone(doc.status)}>{doc.status}</Pill> : null}</>}
      onClose={onClose} wide
      foot={d ? <>
        {ds === 0 && d.can_write && <Btn kind="tint" onClick={() => setEdit(true)}>Edit</Btn>}
        {ds === 1 && d.can_write && meta?.fields.some((f: R) => f.allow_on_submit && !f.read_only) && <Btn kind="tint" onClick={() => setEdit(true)}>Edit</Btn>}
        {ds === 0 && d.can_submit && meta?.is_submittable && <Btn onClick={() => act("Submit", "submit")}>Submit</Btn>}
        {ds === 1 && d.can_cancel && <Btn kind="danger" onClick={() => act("Cancel document", "cancel", true)}>Cancel document</Btn>}
      </> : undefined}>
      {!d && !err && <ListSkel n={6} />}
      {err && <Note tone="bad">{err}</Note>}
      {d && <>
        <Section>Details</Section>
        <List>{shown.map((f) => <Cell key={f.fieldname} label title={f.label} value={label(f)} />)}</List>
        {tables.map((t) => (
          <div key={t.fieldname}><Section>{t.label} · {doc[t.fieldname].length}</Section>
            <List>{doc[t.fieldname].slice(0, 40).map((r: R, i: number) => {
              const cols: R[] = (t.columns || []).filter((c: R) => r[c.fieldname] !== null && r[c.fieldname] !== undefined && r[c.fieldname] !== "" && c.fieldtype !== "Table");
              return <Cell key={i} title={fmtVal(r[cols[0]?.fieldname])} sub={cols.slice(1, 5).map((c: R) => `${c.label}: ${fmtVal(r[c.fieldname])}`).join(" · ")} />;
            })}</List>
            {doc[t.fieldname].length > 40 && <Foot>Showing the first 40 of {doc[t.fieldname].length}.</Foot>}
          </div>
        ))}
        {d.actions?.length > 0 && <><Section>Actions</Section>
          <List>{d.actions.map((a: string) => <Cell key={a} title={slugTitle(a.replace("arinox_" + doctype.toLowerCase().replace(/ /g, "_") + "_", ""))} onClick={() => script(a)} />)}</List>
          <Foot>Every action is checked against the business rules first, and you see what it will do before it does it.</Foot></>}
      </>}
    </Sheet>
  );
}

/* ── list ───────────────────────────────────────────────────────────────── */
export function DocList({ doctype, title }: { doctype: string; title: string }) {
  const cx = useCx();
  const [meta, setMeta] = useState<R | null>(null);
  const [rows, setRows] = useState<R[]>([]);
  const [cols, setCols] = useState<R[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const timer = useRef<number | null>(null);

  const fetchPage = useCallback(async (p: number, search: string, st: string, append: boolean) => {
    setLoading(true);
    const r = await call("cx_doc_list", { doctype, search, status: st, page: p, page_size: 25 });
    setLoading(false);
    if (!r.ok) { setErr(r.error); return; }
    setErr(""); setCols(r.columns); setTotal(r.total); setPage(p);
    setRows((prev) => (append ? [...prev, ...r.rows] : r.rows));
  }, [doctype]);

  useEffect(() => { setRows([]); setQ(""); setStatus(""); setMeta(null); call("cx_doc_meta", { doctype }).then((m) => m.ok && setMeta(m)); void fetchPage(1, "", "", false); }, [doctype, fetchPage, cx.tick]);
  const onSearch = (v: string) => { setQ(v); if (timer.current) window.clearTimeout(timer.current); timer.current = window.setTimeout(() => fetchPage(1, v, status, false), 320); };
  const statusField = meta?.fields.find((f: R) => f.fieldname === "status" && f.fieldtype === "Select");
  const statuses: string[] = statusField ? opts(statusField).slice(0, 8) : [];
  const titleCols = cols.filter((c) => !["name", "docstatus", "status"].includes(c.fieldname));

  return (
    <>
      <Title title={title} sub={total ? `${total.toLocaleString()} record${total === 1 ? "" : "s"}` : undefined}
        right={<div className="cx-row"><button className="cx-icon-btn" aria-label="Refresh" onClick={() => fetchPage(1, q, status, false)}><RefreshCw size={17} /></button>
          {meta?.can_create && <Btn onClick={() => cx.newDoc(doctype)}><Plus size={17} /> New</Btn>}</div>} />
      <div className="cx-search"><Search size={17} /><input className="cx-input" type="search" placeholder={`Search ${title.toLowerCase()}`} value={q} onChange={(e) => onSearch(e.target.value)} /></div>
      {statuses.length > 0 && <div className="cx-mt"><Seg value={status || "All"} options={[{ v: "All", l: "All" }, ...statuses.map((s) => ({ v: s, l: s }))]} onChange={(v) => { const s = v === "All" ? "" : v; setStatus(s); void fetchPage(1, q, s, false); }} /></div>}
      <div className="cx-mt">
        {err && <Note tone="bad">{err}</Note>}
        {loading && rows.length === 0 && <ListSkel />}
        {!loading && !err && rows.length === 0 && <Empty title="Nothing here yet" text={q ? "No record matches your search." : `There are no ${title.toLowerCase()} to show.`}
          action={meta?.can_create ? <Btn onClick={() => cx.newDoc(doctype)}>Create the first one</Btn> : undefined} />}
        {rows.length > 0 && <List>{rows.map((r) => (
          <Cell key={r.name} title={r.name} chev onClick={() => cx.openDoc(doctype, r.name)}
            sub={titleCols.slice(0, 3).map((c) => r[c.fieldname]).filter((v) => v !== null && v !== undefined && v !== "").map(fmtVal).join(" · ")}
            right={r.status ? <Pill tone={tone(r.status)}>{r.status}</Pill> : meta?.is_submittable ? <Pill tone={r.docstatus === 1 ? "green" : r.docstatus === 2 ? "red" : undefined}>{DS[r.docstatus || 0]}</Pill> : undefined} />
        ))}</List>}
        {rows.length < total && <div style={{ textAlign: "center", marginTop: 16 }}><Btn kind="gray" busy={loading} onClick={() => fetchPage(page + 1, q, status, true)}>Show more</Btn></div>}
      </div>
    </>
  );
}
