import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Link2, Lock, PencilLine, Plus, Search, SkipForward } from "lucide-react";
import { callInbox } from "../services/api";
import { Btn, Note, Pill, Sheet, Spinner } from "../cx/ui";

/**
 * Review → edit → confirm, before an order intake writes anything (2026-11-07).
 *
 * Every value approval would send to the ERP is shown here, step by step, and every one of them
 * can be changed. Approval quotes back the hash of the plan as reviewed: if anything changed in
 * between (an edit, a re-read, a change in the ERP) the backend refuses and this sheet reloads.
 * Blocked steps never run; the person has to say, explicitly, that the rest may be created without them.
 *
 * Dropdowns (2026-11-07): `currency` and the buyer are no longer free text. Both read their
 * choices out of the ERP (`get_intake_options`) — the currency list is the site's enabled
 * currencies, the customer list is a live search over the Customer master — and the buyer can be
 * *created* from here by typing the real company name, which is what unblocks a mail whose From
 * header only carried a display name like "temporary".
 */
type R = Record<string, any>;
type Opt = { value: string; label?: string; hint?: string; fallback?: boolean };

const HIDDEN = new Set(["doctype", "name", "owner", "docstatus", "naming_series", "idx"]);
const LONG = new Set(["notes", "description", "from_address", "to_address", "custom_intake_note", "payment_terms_text", "ai_extraction_notes"]);

const pretty = (k: string) => k.replace(/^custom_/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const isScalar = (v: any) => v === null || ["string", "number", "boolean"].includes(typeof v);
const isRows = (v: any) => Array.isArray(v) && v.length > 0 && v.every((x) => x && typeof x === "object" && !Array.isArray(x));
/** Fields whose value is a link to the Customer master, wherever they appear in a payload.
 *  `customer_name` is deliberately NOT here: it is the Opportunity's own text field, and editing it
 *  renames the buyer on the run (functions.intake_plan_edit_core) — which is what a person means. */
const isCustomerField = (k: string) => k === "party_name" || k === "customer";

/** One editable value. Saves on Enter or when the field loses focus, only when it changed. */
function Value({ value, onSave, disabled, long }: { value: any; onSave: (v: any) => Promise<void>; disabled?: boolean; long?: boolean }) {
  const [v, setV] = useState(value === null || value === undefined ? "" : String(value));
  const [busy, setBusy] = useState(false);
  useEffect(() => { setV(value === null || value === undefined ? "" : String(value)); }, [value]);
  const orig = value === null || value === undefined ? "" : String(value);
  const commit = async () => {
    if (v === orig || disabled) return;
    setBusy(true);
    const typed = typeof value === "number" ? (v.trim() === "" ? 0 : Number(v)) : typeof value === "boolean" ? v === "true" || v === "1" : v;
    if (typeof value === "number" && Number.isNaN(typed as number)) { setV(orig); setBusy(false); return; }
    await onSave(typed);
    setBusy(false);
  };
  const common = {
    className: `irv-input${v !== orig ? " is-dirty" : ""}`,
    value: v, disabled: disabled || busy,
    onChange: (e: any) => setV(e.target.value),
    onBlur: commit,
    "aria-label": "value",
  };
  return long
    ? <textarea {...common} rows={2} />
    : <input {...common} inputMode={typeof value === "number" ? "decimal" : undefined}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setV(orig); }} />;
}

/** A fixed list from the ERP (currencies). Keeps a value the site no longer lists instead of losing it. */
function Select({ value, options, onSave, disabled }: { value: any; options: Opt[]; onSave: (v: string) => Promise<void>; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  const cur = value === null || value === undefined ? "" : String(value);
  const known = options.some((o) => o.value === cur);
  return (
    <select className={`irv-input irv-select${cur ? "" : " is-empty"}`} value={cur} disabled={disabled || busy || !options.length}
      aria-label="choose from the ERP list"
      onChange={async (e) => { const nv = e.target.value; setBusy(true); await onSave(nv); setBusy(false); }}>
      {!cur && <option value="">{options.length ? "— choose —" : "reading the ERP…"}</option>}
      {!!cur && !known && <option value={cur}>{cur} — not in the ERP list</option>}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label && o.label !== o.value ? `${o.value} — ${o.label}` : o.value}</option>)}
    </select>
  );
}

/**
 * The buyer, as a choice rather than a guess: search the Customer master, or type the real company
 * name and let approval create it. Both answers go through `set_intake_customer`, which rewrites
 * the buyer on the run and rebuilds the plan — so the Customer step and the Opportunity agree.
 */
function CustomerPick({ runId, current, proposed, candidates, onDone, disabled, compact }:
  { runId: number; current?: string; proposed?: string; candidates?: { name: string; score?: number }[];
    onDone: (msg: string) => void; disabled?: boolean; compact?: boolean }) {
  const [open, setOpen] = useState(!compact);
  const [q, setQ] = useState("");
  const [list, setList] = useState<Opt[]>([]);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState<"" | "link" | "create">("");
  const [err, setErr] = useState("");
  const [newName, setNewName] = useState(proposed || "");
  const box = useRef<HTMLDivElement | null>(null);
  const search = useRef<HTMLInputElement | null>(null);

  useEffect(() => { if (open) setTimeout(() => search.current?.focus(), 30); }, [open]);
  useEffect(() => { setNewName((n) => n || proposed || ""); }, [proposed]);
  useEffect(() => {
    if (!open) return;
    let dead = false;
    setReading(true);
    const t = setTimeout(async () => {
      const r = await callInbox("get_intake_options", { kind: "customer", q, limit: 20 });
      if (dead) return;
      const opts = r.data?.options;
      setList(Array.isArray(opts) ? opts : []);
      setReading(false);
    }, 220);
    return () => { dead = true; clearTimeout(t); };
  }, [q, open]);
  useEffect(() => {
    if (!compact) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [compact]);

  const link = async (name: string) => {
    setBusy("link"); setErr("");
    const r = await callInbox("set_intake_customer", { run_id: runId, customer: name });
    setBusy("");
    const d: R = r.data || {};
    if (d.ok === false) { setErr(d.error === "customer_not_found" ? `${name} is not in the ERP any more.` : (d.error || "The ERP refused that link.")); return; }
    setOpen(false);
    onDone(`Customer linked — ${name}. The plan was rebuilt with it.`);
  };
  const create = async () => {
    const nm = newName.trim();
    if (nm.length < 2) { setErr("Type the company name as it should appear in the ERP."); return; }
    setBusy("create"); setErr("");
    const r = await callInbox("set_intake_customer", { run_id: runId, create: 1, name: nm });
    setBusy("");
    const d: R = r.data || {};
    if (d.ok === false) { setErr(d.error === "name_too_short" ? "That name is too short." : (d.error || "The plan could not be rebuilt.")); return; }
    setOpen(false);
    onDone(d.note || `The Customer step will create “${nm}”.`);
  };

  const panel = (
    <div className={`irv-pick__panel${compact ? "" : " is-static"}`}>
      <div className="irv-pick__search">
        <Search size={13} />
        <input ref={search} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the Customer master…"
          onKeyDown={(e) => { if (e.key === "Escape") { setOpen(false); } if (e.key === "Enter" && list[0]) void link(list[0].value); }} />
        {reading && <Spinner />}
      </div>
      {(candidates || []).length > 0 && (
        <div className="irv-pick__hint">
          Looks like{" "}
          {(candidates || []).map((c) => (
            <button key={c.name} type="button" className="irv-chip" disabled={!!busy} onClick={() => void link(c.name)}>
              {c.name}{typeof c.score === "number" ? ` · ${Math.round(c.score * 100)}%` : ""}
            </button>
          ))}
        </div>
      )}
      <div className="irv-pick__list" role="listbox">
        {list.length === 0 && !reading && <div className="irv-pick__empty">{q ? "No Customer matches that." : "No Customers in the ERP yet — create the first one below."}</div>}
        {list.map((o) => (
          <button key={o.value} type="button" role="option" aria-selected={o.value === current}
            className={`irv-pick__row${o.value === current ? " is-on" : ""}`} disabled={!!busy} onClick={() => void link(o.value)}>
            <Link2 size={12} />
            <b>{o.label || o.value}</b>
            {o.hint ? <small>{o.hint}</small> : null}
            {o.value === current && <Check size={12} />}
          </button>
        ))}
      </div>
      <div className="irv-pick__new">
        <Plus size={13} />
        <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="…or type the new company name"
          disabled={!!busy} onKeyDown={(e) => { if (e.key === "Enter") void create(); }} />
        <Btn sm kind="tint" busy={busy === "create"} disabled={!!busy || newName.trim().length < 2} onClick={() => void create()}>
          Create this Customer
        </Btn>
      </div>
      <div className="irv-pick__foot">
        {err ? <span className="irv-pick__err">{err}</span>
          : <span>Linking uses a Customer the ERP already has. Creating is for a buyer that is genuinely new — it is still only a draft until you approve.</span>}
      </div>
    </div>
  );

  if (!compact) return panel;
  return (
    <div className="irv-pick" ref={box}>
      <button type="button" className={`irv-input irv-pick__btn${disabled ? " is-off" : ""}`} disabled={disabled}
        onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Link2 size={12} />
        <span className={current ? "" : "is-none"}>{current || (proposed ? `create “${proposed}”` : "choose a Customer")}</span>
        <ChevronDown size={12} />
      </button>
      {open && panel}
    </div>
  );
}

function Rows({ rows, path, onSave, disabled }: { rows: R[]; path: string; onSave: (p: string, v: any) => Promise<void>; disabled?: boolean }) {
  const cols = useMemo(() => {
    const seen: string[] = [];
    rows.forEach((r) => Object.keys(r).forEach((k) => { if (!HIDDEN.has(k) && isScalar(r[k]) && !seen.includes(k)) seen.push(k); }));
    return seen.slice(0, 12);
  }, [rows]);
  return (
    <div className="irv-tablewrap">
      <table className="irv-table">
        <thead><tr><th>#</th>{cols.map((c) => <th key={c}>{pretty(c)}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => (
          <tr key={i}><td className="irv-idx">{i + 1}</td>
            {cols.map((c) => <td key={c}><Value value={r[c] ?? ""} disabled={disabled} onSave={(v) => onSave(`${path}.${i}.${c}`, v)} /></td>)}
          </tr>))}
        </tbody>
      </table>
    </div>
  );
}

export function IntakeReview({ runId, onClose, onDone }: { runId: number; onClose: () => void; onDone: (msg: string) => void }) {
  const [data, setData] = useState<R | null>(null);
  const [err, setErr] = useState("");
  const [accept, setAccept] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [flash, setFlash] = useState("");
  const [currencies, setCurrencies] = useState<Opt[]>([]);

  const load = useCallback(async () => {
    setErr("");
    const r = await callInbox("intake_review", { run_id: runId });
    const d: R = r.data || {};
    if (d.ok === false || !Array.isArray(d.steps)) { setErr(d.error || r.message || "The plan could not be read."); setData(null); return; }
    setData(d);
    if (Array.isArray(d.options?.currency)) setCurrencies(d.options.currency);
    setOpen((o) => {
      if (Object.keys(o).length) return o;
      const rows = d.steps as R[];
      // a blocked buyer is the one thing a person must answer, so it opens first
      const badBuyer = rows.find((s) => s.key === "customer" && s.status === "blocked");
      const first = badBuyer || rows.find((s) => s.status !== "blocked" && s.status !== "skipped" && s.kind !== "reuse");
      return first ? { [first.key]: true } : {};
    });
  }, [runId]);
  useEffect(() => { void load(); }, [load]);

  /* The currency list is the site's own — fetched once, and only if the plan did not carry it. */
  useEffect(() => {
    if (currencies.length) return;
    let dead = false;
    callInbox("get_intake_options", { kind: "currency" }).then((r) => {
      if (dead) return;
      const opts = r.data?.options;
      if (Array.isArray(opts)) setCurrencies(opts);
    });
    return () => { dead = true; };
  }, [currencies.length]);

  const edit = useCallback(async (stepKey: string, field: string, value: any) => {
    const r = await callInbox("intake_plan_edit", { run_id: runId, step_key: stepKey, field, value });
    const d: R = r.data || {};
    if (d.ok === false) { setFlash(`Not changed: ${d.error || "refused"}`); return; }
    if (Array.isArray(d.steps)) setData(d);
    setConfirming(false);
    setFlash(d.note || `${pretty(field.split(".").slice(-1)[0])} updated — the plan was rebuilt with your value.`);
  }, [runId]);

  const afterBuyer = useCallback((msg: string) => { setFlash(msg); setConfirming(false); void load(); }, [load]);

  const steps: R[] = data?.steps || [];
  const blocked: R[] = data?.blocked || [];
  const buyer: R = data?.buyer || {};
  const willRun = steps.filter((s) => s.status !== "blocked" && s.status !== "skipped");
  const creates = willRun.filter((s) => s.kind !== "reuse" && !s.existing).length;

  const approve = async () => {
    if (!data) return;
    setRunning(true);
    const r = await callInbox("approve_intake", { run_id: runId, review_hash: data.review_hash, accept_blocked: accept ? 1 : 0 });
    const d: R = r.data || {};
    setRunning(false);
    setConfirming(false);
    if (d.needs_review) { setFlash(d.error || "The plan changed — please look again."); await load(); return; }
    if (d.ok === false && !d.refs?.length) { setErr(d.error || d.note || "The ERP refused the drafts."); return; }
    const made = (d.refs || []).map((x: R) => `${x.doctype} ${x.name}`).join(", ");
    onDone(d.ok ? `Created in the ERP: ${made || "nothing new (already on file)"}` : `Partly done — ${made || "nothing created"}. ${String(d.note || "").split("\n").slice(-2).join(" ")}`);
  };

  const statusPill = (s: R) => s.status === "blocked" ? <Pill tone="orange"><Lock size={11} /> blocked</Pill>
    : s.status === "skipped" ? <Pill><SkipForward size={11} /> not used here</Pill>
    : s.kind === "reuse" || s.existing ? <Pill tone="blue"><Link2 size={11} /> links {s.existing || s.payload?.existing || "existing"}</Pill>
    : <Pill tone="green"><Check size={11} /> will create</Pill>;

  const foot = data ? (
    <div className="irv-foot">
      {blocked.length > 0 && (
        <label className="irv-accept">
          <input type="checkbox" checked={accept} onChange={(e) => { setAccept(e.target.checked); setConfirming(false); }} />
          <span>Create the rest without the {blocked.length} blocked step{blocked.length === 1 ? "" : "s"}</span>
        </label>
      )}
      <span style={{ flex: 1 }} />
      <Btn kind="gray" onClick={onClose}>Not now</Btn>
      {!confirming
        ? <Btn disabled={!willRun.length || (blocked.length > 0 && !accept)} onClick={() => setConfirming(true)}>Approve…</Btn>
        : <Btn busy={running} onClick={approve}><CheckCircle2 size={15} /> Yes, create {creates} draft{creates === 1 ? "" : "s"} in the ERP</Btn>}
    </div>
  ) : undefined;

  return (
    <Sheet wide title="Check everything, then approve" sub={`Intake #${runId} · nothing is written until you confirm`} onClose={onClose} foot={foot}>
      {!data && !err && <div style={{ padding: 28, textAlign: "center" }}><Spinner /><p className="cx-lead">Rebuilding the plan against the ERP…</p></div>}
      {err && <Note tone="bad">{err}</Note>}
      {data && <>
        <div className="irv-summary">
          <div><b>{willRun.length}</b><span>step{willRun.length === 1 ? "" : "s"} will run</span></div>
          <div><b>{creates}</b><span>new draft{creates === 1 ? "" : "s"}</span></div>
          <div className={blocked.length ? "is-warn" : ""}><b>{blocked.length}</b><span>blocked</span></div>
          <div><b>{(data.skipped || []).length}</b><span>not used on this ERP</span></div>
        </div>
        {flash && <Note tone="ok">{flash}</Note>}
        {(data.missing || []).length > 0 && <Note tone="warn">Not found on the paper: {(data.missing as string[]).join(" · ")}. Fill them below if the ERP needs them.</Note>}
        {confirming && <Note tone="warn">Last check: this creates {creates} draft record{creates === 1 ? "" : "s"} in the ERP{blocked.length ? `, and skips ${blocked.length} blocked step${blocked.length === 1 ? "" : "s"}` : ""}. Drafts can be rolled back from this screen.</Note>}

        <div className="irv-steps">
          {steps.map((s) => {
            const pl: R = s.payload || {};
            const editable = s.status !== "blocked" && s.status !== "skipped" && s.kind !== "reuse" && s.kind !== "skip";
            const scalars = Object.entries(pl).filter(([k, v]) => !HIDDEN.has(k) && isScalar(v) && k !== "existing");
            const tables = Object.entries(pl).filter(([k, v]) => !HIDDEN.has(k) && isRows(v));
            const isOpen = !!open[s.key];
            const isBuyerStep = s.key === "customer";
            const linked = isBuyerStep ? (pl.existing || s.existing || buyer.customer || "") : (buyer.customer || "");
            const proposedName = isBuyerStep ? (pl.customer_name || buyer.name || "") : (buyer.name || "");
            return (
              <section key={s.key} className={`irv-step irv-step--${s.status === "blocked" ? "blocked" : s.status === "skipped" ? "skipped" : "ok"}`}>
                <button className="irv-step__head" onClick={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))} aria-expanded={isOpen}>
                  <span className="irv-step__n">{s.seq}</span>
                  <span className="irv-step__t"><b>{s.label}</b><small>{s.doctype}{(s.edited || []).length ? ` · ${s.edited.length} value(s) changed by you` : ""}</small></span>
                  {statusPill(s)}
                </button>
                {s.reason && <div className={`irv-step__reason${s.status === "blocked" ? " is-bad" : ""}`}>{s.status === "blocked" && <AlertTriangle size={13} />} {s.reason}</div>}
                {/* the buyer gate: a choice from the Customer master, or a new company typed here */}
                {isOpen && isBuyerStep && s.status !== "skipped" && (
                  <div className="irv-step__body">
                    <div className="irv-buyerline">
                      {linked ? <>Linked to <b>{linked}</b></> : <>Will create <b>{proposedName || "—"}</b> on approval</>}
                      {buyer.email ? <span className="irv-dim"> · mail from {buyer.email}</span> : null}
                    </div>
                    <CustomerPick runId={runId} current={linked} proposed={proposedName}
                      candidates={buyer.candidates || []} onDone={afterBuyer} />
                  </div>
                )}
                {isOpen && editable && (scalars.length > 0 || tables.length > 0) && (
                  <div className="irv-step__body">
                    {scalars.length > 0 && <div className="irv-grid">
                      {scalars.map(([k, v]) => (
                        <label key={k} className={`irv-field${LONG.has(k) ? " is-long" : ""}`}>
                          <span>{pretty(k)}{(s.edited || []).includes(k) && <PencilLine size={11} className="irv-mark" />}</span>
                          {k === "currency"
                            ? <Select value={v} options={currencies} onSave={(nv) => edit(s.key, k, nv)} />
                            : isCustomerField(k)
                              ? <CustomerPick compact runId={runId} current={String(v || "")} proposed={proposedName}
                                  candidates={buyer.candidates || []} onDone={afterBuyer} />
                              : <Value value={v} long={LONG.has(k)} onSave={(nv) => edit(s.key, k, nv)} />}
                        </label>
                      ))}
                    </div>}
                    {tables.map(([k, rows]) => (
                      <div key={k} className="irv-rows">
                        <div className="irv-rows__h">{pretty(k)} · {(rows as R[]).length} row{(rows as R[]).length === 1 ? "" : "s"}</div>
                        <Rows rows={rows as R[]} path={k} onSave={(p, nv) => edit(s.key, p, nv)} />
                      </div>
                    ))}
                  </div>
                )}
                {isOpen && editable && scalars.length === 0 && tables.length === 0 && <div className="irv-step__reason">Nothing to fill in for this step.</div>}
              </section>
            );
          })}
        </div>
        <p className="irv-help">Click a step to see and change exactly what it will write. Currency and the buyer come from the ERP's own lists — your changes are kept even if the mail is read again.</p>
      </>}
    </Sheet>
  );
}
