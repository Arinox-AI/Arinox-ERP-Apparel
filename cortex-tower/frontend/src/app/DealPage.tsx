import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ArrowLeft, ArrowRight, Calculator, Check, Database, ExternalLink, FileSignature, Mail, MessageSquare, Plus, RefreshCw, Send, ShoppingBag, Sparkles, Trash2, Upload } from "lucide-react";
import { Badge, Btn, Card, Empty, Field, Input, Loading, Modal, Note, Select, StageBadge, Textarea, call, day, money, num, useCall, useToast, when } from "./kit";
import type { R } from "./kit";
import { CustomerPicker } from "./CustomerPicker";
import { MATERIAL_TYPES } from "./CostSheetTab";
import { useCx } from "../cx/ui";

const STEPS = [
  { k: "inquiry", l: "Inquiry", s: "Styles & BOM" },
  { k: "costing", l: "Costing", s: "Price each style" },
  { k: "quote", l: "Quote", s: "Send in the thread" },
  { k: "reply", l: "Buyer's answer", s: "Counter / agree" },
  { k: "contract", l: "Contract", s: "Sizes, dates, terms" },
  { k: "order", l: "Sales order", s: "Then production" },
  { k: "track", l: "Ship & track", s: "Papers, dates, tracking" },
];
const STAGE_STEP: Record<string, number> = { inquiry: 0, costing: 1, quoted: 3, negotiating: 3, accepted: 4, contract: 4, order: 5, lost: 3 };

/* Confirming a Tech Pack or a Cost Sheet is an ERP action: the ERP has its own screen for it, its own rules about who
   may submit, and its own audit. So the tower links to that page instead of pretending to be it. */
function ErpBtn({ url, label = "Confirm in the ERP", sm = true, kind = "ghost" }: { url?: string; label?: string; sm?: boolean; kind?: "ghost" | "primary" | "plain" | "dark" }) {
  if (!url) return null;
  return <Btn sm={sm} kind={kind as any} title={`Open this in the ERP (${url})`} onClick={() => window.open(url, "_blank", "noopener")}>
    <ExternalLink size={13} /> {label}
  </Btn>;
}

/* THE PAGE THIS STEP IS ABOUT, resolved by the backend and never assembled here.
   `deals.erp_status` answers with `by_step` (one ERP page per step: the step's own document, or that DocType's list while
   the document does not exist yet) and `focus` (the page of the step the deal is on). So an "open the ERP" button lands
   on the Sales Order you were looking at, and not on the ERP's front page - the 2026-11-09 report - and there is exactly
   one place in the product that knows how an ERP address is spelled. */
function erpPage(erp: R | undefined, step?: string): { url?: string; label: string; short: string } {
  const e = erp || {};
  const page = (step && (e.by_step || {})[step]) || e.focus || {};
  return { url: page.url || e.base_url, label: page.label || "Open the ERP",
           short: page.doctype ? `Open ${page.doctype}` : "Open the ERP" };
}

export function DealPage({ id, go }: { id: number; go: (p: string) => void }) {
  const toast = useToast();
  const r = useCall("deal_get", { deal_id: id, erp: true }, []);
  const [view, setView] = useState<number | null>(null);
  const deal: R | undefined = r.data?.deal;
  const ptypes: string[] = r.data?.product_types || [];
  const setDeal = (d: R) => r.setData({ ...(r.data || {}), deal: d });
  const reload = () => r.reload(true);

  const nowStep = useMemo(() => {
    if (!deal) return 0;
    const n = deal.next?.step;
    const map: Record<string, number> = { inquiry: 0, costing: 1, quote: 2, reply: 3, contract: 4, order: 5, after: 5, done: 3 };
    return n && n in map ? map[n] : STAGE_STEP[deal.stage] ?? 0;
  }, [deal]);
  useEffect(() => { setView(null); }, [id]);
  const shown = view ?? nowStep;
  useEffect(() => { document.querySelector(".ws-main")?.scrollTo({ top: 0, behavior: "smooth" }); }, [shown]);
  if (r.loading && !r.data) return <div className="ws-page"><Loading rows={5} /></div>;
  if (r.error || !deal) return <div className="ws-page"><Note tone="bad">{r.error || "Deal not found."}</Note><div className="ws-mt"><Btn onClick={() => go("deals")}>Back to deals</Btn></div></div>;
  const step = view ?? nowStep;
  const att = deal.attention;

  return (
    <div className="ws-page">
      <div className="ws-row" style={{ marginBottom: 10 }}>
        <Btn kind="plain" sm onClick={() => go("deals")}><ArrowLeft size={14} /> Deals</Btn>
        {deal.thread_key && <Btn kind="plain" sm onClick={() => go(`inbox/${encodeURIComponent(deal.thread_key)}`)}><Mail size={14} /> Conversation</Btn>}
        <span style={{ marginLeft: "auto" }} className="ws-small ws-muted">Updated {when(deal.updated_at)}</span>
        <Btn sm icon title="Refresh from the ERP" onClick={reload}><RefreshCw size={14} /></Btn>
      </div>
      <div className="ws-head" style={{ marginBottom: 14 }}>
        <div style={{ minWidth: 0 }}>
          <div className="ws-row"><StageBadge stage={deal.stage} label={deal.stage_label} /><span className="ws-muted ws-small">{deal.customer_name || "No customer yet"}</span></div>
          <h2 style={{ marginTop: 6 }}>{deal.title}</h2>
        </div>
        <div className="ws-head__acts" style={{ alignItems: "center", gap: 18 }}>
          <div className="ws-right"><div className="ws-small ws-muted">Quantity</div><b className="ws-mono">{num(deal.total_qty)} pcs</b></div>
          <div className="ws-right"><div className="ws-small ws-muted">Value</div><b className="ws-mono">{deal.total_value ? money(deal.total_value, deal.currency) : "—"}</b></div>
        </div>
      </div>

      <div className="ws-next" style={{ marginBottom: 12 }}>
        <ArrowRight size={18} />
        <div style={{ flex: 1 }}><b>{deal.next?.text}</b>{att && <div><span>{att.text}</span></div>}</div>
        {step !== nowStep && <Btn sm kind="ghost" onClick={() => setView(null)}>Go to this step</Btn>}
      </div>

      <div className="ws-steps" role="tablist" aria-label="Deal steps">
        {STEPS.map((s, i) => (
          <button key={s.k} role="tab" aria-selected={i === step} className={`ws-step${i < nowStep ? " is-done" : ""}${i === nowStep && deal.stage !== "lost" ? " is-now" : ""}${i === step ? " is-view" : ""}`} onClick={() => setView(i)}>
            <span className="ws-step__n">{i < nowStep ? <Check size={12} /> : i + 1}</span>
            <span className="ws-step__l">{s.l}</span><span className="ws-step__s">{s.s}</span>
          </button>))}
      </div>

      <div className="ws-grid ws-grid--side ws-mt">
        <div className="ws-stack">
          {step === 0 && <InquiryStep deal={deal} ptypes={ptypes} erp={r.data?.erp || {}} setDeal={setDeal} toast={toast} toCosting={() => setView(1)} />}
          {step === 1 && <CostingStep deal={deal} erp={r.data?.erp || {}} setDeal={setDeal} reload={reload} toast={toast} go={go} />}
          {step === 2 && <QuoteStep deal={deal} setDeal={setDeal} toast={toast} />}
          {step === 3 && <ReplyStep deal={deal} setDeal={setDeal} toast={toast} go={go} />}
          {step === 4 && <ContractStep deal={deal} erp={r.data?.erp || {}} setDeal={setDeal} toast={toast} />}
          {step === 5 && <OrderStep deal={deal} erp={r.data?.erp || {}} setDeal={setDeal} toast={toast} go={go} reload={reload} />}
          {step === 6 && deal.refs?.sales_order && <OpenOrder so={deal.refs.sales_order} go={go} label="Ship and track: open the order's Ship step" step="ship" />}
          {step === 6 && <Card title="Ship & track"><Note>{deal.refs?.sales_order ? "Shipping moved to the Order page: the shipment wizard, the four clocks, the papers the contract names and the trade term are all in the order's Ship step. Use the button above."
            : "Shipping is tracked on the Order page once the Sales Order exists (step 6 of this deal)."}</Note></Card>}
        </div>
        <SidePanel deal={deal} erp={r.data?.erp || {}} />
      </div>
    </div>
  );
}

type StepProps = { deal: R; setDeal: (d: R) => void; toast: (m: string, t?: "ok" | "bad") => void };

/* ───────────────────────── 1 · inquiry ───────────────────────── */
function InquiryStep({ deal, ptypes, erp, setDeal, toast, toCosting }: StepProps & { ptypes: string[]; erp: R; toCosting: () => void }) {
  const registered = !!deal.refs?.opportunity;
  const [f, setF] = useState<R>(() => pick(deal));
  const [styles, setStyles] = useState<R[]>(() => deal.styles.map((s: R) => ({ ...s })));
  const [bomOpen, setBomOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const dirty = JSON.stringify(f) !== JSON.stringify(pick(deal)) || JSON.stringify(styles) !== JSON.stringify(deal.styles);
  useEffect(() => { setF(pick(deal)); setStyles(deal.styles.map((s: R) => ({ ...s }))); }, [deal]);

  const save = async (): Promise<R | null> => {
    setBusy("save");
    const r = await call("deal_update", { deal_id: deal.id, patch: { ...f, styles } });
    setBusy("");
    if (!r.ok) { toast(r.error || "Not saved.", "bad"); return null; }
    setDeal(r.deal); return r.deal;
  };
  const register = async () => {
    if (dirty && !(await save())) return;
    setBusy("register");
    const r = await call("deal_register", { deal_id: deal.id });
    setBusy("");
    if (!r.ok) { toast(r.error || "The ERP refused it.", "bad"); return; }
    setDeal(r.deal);
    toast(`In the ERP: ${r.deal.refs.opportunity} and ${r.deal.styles.filter((s: R) => s.tech_pack).length} Tech Pack(s). Next: costing.`);
  };
  const setStyle = (i: number, k: string, v: any) => setStyles((ss) => ss.map((s, j) => (j === i ? { ...s, [k]: v } : s)));
  const live = styles.filter((s) => s.status !== "dropped");

  return (
    <>
      <Card title="Customer" right={registered ? <Badge tone="ok">In the ERP</Badge> : null}>
        {registered ? <div><b>{deal.customer_name || deal.customer}</b></div> : (
          <>
            {deal.attention?.kind === "customer" && <div style={{ marginBottom: 10 }}><Note tone="warn">{deal.attention.text}</Note></div>}
            <CustomerPicker value={deal.customer} suggestName={deal.attention?.suggest} email={deal.contact_email} contactName={deal.contact_name} dealId={deal.id}
              onPicked={async (c, name) => {
                const r = await call("deal_update", { deal_id: deal.id, patch: { customer: c, customer_name: name || c } });
                if (r.ok) { setDeal(r.deal); toast(`Customer set to ${name || c}.`); } else toast(r.error, "bad");
              }} />
          </>
        )}
      </Card>

      <Card title="Inquiry details" sub="As read from the buyer's mail. Correct anything; no price is needed at this stage.">
        <div className="ws-form">
          <Field label="Title" wide><Input value={f.title} onChange={(v) => setF({ ...f, title: v })} /></Field>
          <Field label="Season"><Input value={f.season} onChange={(v) => setF({ ...f, season: v })} placeholder="e.g. SUMMER 2027" /></Field>
          <Field label="Currency"><Select value={f.currency} onChange={(v) => setF({ ...f, currency: v })} options={["USD", "EUR", "GBP", "INR", "VND", "HKD", "CNY"]} disabled={registered} /></Field>
          <Field label="Incoterm"><Select value={f.incoterm} onChange={(v) => setF({ ...f, incoterm: v })} placeholder="—" options={["FOB", "DDP", "CIF", "CFR", "EXW", "FCA", "DAP", "LDP"]} /></Field>
          <Field label="Destination / port"><Input value={f.destination} onChange={(v) => setF({ ...f, destination: v })} placeholder="e.g. Los Angeles" /></Field>
          <Field label="Ex-factory" hint={f.ex_factory ? day(f.ex_factory) : "Buyer's target"}><Input type="date" value={f.ex_factory} onChange={(v) => setF({ ...f, ex_factory: v })} /></Field>
          <Field label="In-warehouse"><Input type="date" value={f.in_warehouse} onChange={(v) => setF({ ...f, in_warehouse: v })} /></Field>
          <Field label="Notes" wide><Textarea rows={2} value={f.notes || ""} onChange={(v) => setF({ ...f, notes: v })} placeholder="Anything to remember about this inquiry" /></Field>
        </div>
      </Card>

      <Card title={`Styles (${live.length})`} sub="One Tech Pack is made per style, with the buyer's BOM lines." flush
        right={!registered ? <Btn sm onClick={() => setStyles([...styles, { key: `new${Date.now()}`, style_no: "", style_name: "", qty: "", bom: [], sizes: [], status: "open", product_type: ptypes[0] || "" }])}><Plus size={13} /> Add style</Btn> : null}>
        <div className="ws-table-wrap">
          <table className="ws-table ws-table--edit">
            <thead><tr><th>Style no.</th><th>Description</th><th>Colour</th><th>Fabric</th><th className="num">Qty</th><th>Product type</th><th>Sizes</th><th /></tr></thead>
            <tbody>{styles.map((s, i) => s.status === "dropped" ? null : (
              <tr key={s.key}>
                <td style={{ minWidth: 140 }}><Input sm value={s.style_no} onChange={(v) => setStyle(i, "style_no", v.toUpperCase())} disabled={!!s.tech_pack} aria-label="Style number" /></td>
                <td style={{ minWidth: 170 }}><Input sm value={s.style_name} onChange={(v) => setStyle(i, "style_name", v)} aria-label="Description" /></td>
                <td style={{ minWidth: 110 }}><Input sm value={s.colour} onChange={(v) => setStyle(i, "colour", v)} aria-label="Colour" /></td>
                <td style={{ minWidth: 130 }}><Input sm value={s.fabric} onChange={(v) => setStyle(i, "fabric", v)} aria-label="Fabric" /></td>
                <td style={{ width: 90 }}><Input sm num type="number" value={s.qty ?? ""} onChange={(v) => setStyle(i, "qty", v)} aria-label="Quantity" /></td>
                <td style={{ minWidth: 120 }}><Select sm value={s.product_type} onChange={(v) => setStyle(i, "product_type", v)} placeholder="Choose…" options={ptypes} disabled={!!s.tech_pack} /></td>
                <td style={{ minWidth: 110 }}><Input sm value={(s.sizes || []).join(", ")} onChange={(v) => setStyle(i, "sizes", v.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean))} placeholder="S, M, L" aria-label="Sizes" /></td>
                <td>{s.tech_pack ? <Badge tone="ok" title={s.tech_pack}>TP</Badge> : <Btn sm icon kind="plain" title="Remove style" onClick={() => setStyles(styles.filter((_, j) => j !== i))}><Trash2 size={13} /></Btn>}</td>
              </tr>))}</tbody>
          </table>
        </div>
        {!styles.length && <Empty title="No styles yet" text="Add the styles the buyer asked about." />}
      </Card>

      <div className="ws-row" style={{ justifyContent: "flex-end" }}>
        {dirty && <span className="ws-small ws-muted">Unsaved changes</span>}
        <Btn busy={busy === "save"} disabled={!dirty} onClick={save}>Save</Btn>
        <Btn kind="primary" busy={busy === "register"} onClick={register}><Upload size={14} /> {registered ? "Send new styles to the ERP" : "Send the inquiry to the ERP"}</Btn>
      </div>

      {/* The buyer's sheet is the answer to "what is this style, and what is it made of" - show it here, not
          only behind a button. */}
      <MailDocuments deal={deal} setDeal={setDeal} toast={toast} />
      <Materials deal={deal} onEdit={(k) => setBomOpen(k)} />
      <Specification deal={deal} />
      {registered && <Note tone="ok">
        <div>This inquiry is in the ERP as <b>{deal.refs.opportunity}</b>, with a Tech Pack per style. The material
          lines below went into each Tech Pack&rsquo;s <b>Buyer BOM</b> tab — that tab is the ERP&rsquo;s home for the
          buyer&rsquo;s requirement list, not the pack&rsquo;s spec (measurements, construction and wash &amp; care stay
          their own sections, and nothing here writes them). Costing copies the lines onto the Cost Sheet, and the
          manufacturing <b>BOM</b> document is made from the style at production time, when quantities and buying rates
          are settled.</div>
        <div className="ws-row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          {live.filter((s) => s.tech_pack).map((s) => (
            <ErpBtn key={s.key} kind="primary" label={`Confirm ${s.tech_pack} in the ERP`}
              url={(erp[`tech_pack:${s.tech_pack}`] || {}).url} />
          ))}
          <ErpBtn label={erpPage(erp, "inquiry").label} url={erpPage(erp, "inquiry").url} />
          <Btn sm onClick={toCosting}>Go to costing</Btn>
        </div>
      </Note>}
      {live.some((s) => (s.warnings || []).some((w: string) => w.startsWith("Style item"))) && <Note tone="warn">
        <b>The ERP could not make the style Items</b> (needed later for the contract and the Sales Order): {live.find((s) => (s.warnings || []).some((w: string) => w.startsWith("Style item")))?.warnings.find((w: string) => w.startsWith("Style item")).replace("Style item not made yet: ", "")} You can carry on costing; fix this before the contract.</Note>}
      {bomOpen && <BomEditor deal={deal} styleKey={bomOpen} style={styles.find((s) => s.key === bomOpen)!} locked={!!styles.find((s) => s.key === bomOpen)?.tech_pack}
        onDeal={setDeal} toast={toast}
        onClose={() => setBomOpen(null)} onSave={(bom) => { setStyles((ss) => ss.map((s) => (s.key === bomOpen ? { ...s, bom } : s))); setBomOpen(null); }} />}
    </>
  );
}

function pick(d: R): R {
  const o: R = {};
  for (const k of ["title", "season", "currency", "incoterm", "destination", "ex_factory", "in_warehouse", "notes"]) o[k] = d[k] ?? "";
  return o;
}

/* The BOM lines, on the inquiry page. A merchandiser is looking at this sheet to answer "what is this garment made
   of, and how much of it per piece" - that should not be hidden behind a button. Edit opens the same editor. */
function Materials({ deal, onEdit }: { deal: R; onEdit: (key: string) => void }) {
  const live = (deal.styles || []).filter((s: R) => s.status !== "dropped");
  const lines = live.reduce((n: number, s: R) => n + (s.bom || []).length, 0);
  /** What the whole order needs of one line: consumption per garment x the order quantity. */
  const need = (r: R, qty: number) => (r.consumption === null || r.consumption === undefined || r.consumption === "" || !qty
    ? null : Number(r.consumption) * qty);
  const totals = (s: R) => {
    const qty = Number(s.qty || 0);
    const by: Record<string, number> = {};
    for (const r of s.bom || []) {
      const n = need(r, qty);
      if (n === null) continue;
      const u = (r.uom || "—") as string;
      by[u] = (by[u] || 0) + n;
    }
    return { qty, by };
  };
  return (
    <Card title={<span style={{ whiteSpace: "nowrap" }}>Bill of materials</span>} flush
      sub={`${lines} line(s) · what is needed and how much, per garment and for the order. In the ERP these fill each style's Tech Pack on the "Buyer BOM" tab.`}
      right={<span className="ws-small ws-muted">from the buyer&rsquo;s BOM</span>}>
      {live.map((s: R) => (
        <div key={s.key} style={{ padding: "12px 16px", borderTop: "1px solid var(--ws-line, #eceff3)" }}>
          <div className="ws-row" style={{ marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
            <b className="ws-mono">{s.style_no || "New style"}</b>
            {s.style_name ? <span className="ws-small">{s.style_name}</span> : null}
            <Badge tone={(s.bom || []).length ? "ok" : "warn"}>{(s.bom || []).length} lines</Badge>
            {s.bom_file ? <span className="ws-small ws-muted">from {s.bom_file}</span> : null}
            <span style={{ marginLeft: "auto" }}>
              <Btn sm kind="plain" onClick={() => onEdit(s.key)}>{(s.bom || []).length ? "Edit BOM" : "Add the BOM"}</Btn>
            </span>
          </div>
          {(s.warnings || []).length > 0 && <div style={{ marginBottom: 8 }}><Note tone="warn">{(s.warnings || []).join(" · ")}</Note></div>}
          {(s.bom || []).length ? (() => {
            const t = totals(s);
            const units = Object.entries(t.by);
            return (
            <div className="ws-table-wrap">
              <table className="ws-table">
                <thead><tr><th>Type</th><th>Buyer code</th><th>Description</th><th>Colour</th><th>UOM</th><th className="num">Per garment</th>
                  <th className="num">For {t.qty ? `${num(t.qty)} pcs` : "the order"}</th></tr></thead>
                <tbody>{(s.bom || []).map((r: R, i: number) => {
                  const n = need(r, t.qty);
                  return (
                  <tr key={`${r.item_code}-${i}`}>
                    <td>{r.material_type || "Other"}</td>
                    <td className="ws-mono">{r.item_code || "—"}</td>
                    <td>{r.description || "—"}</td>
                    <td>{r.colour || "—"}</td>
                    <td>{r.uom || "—"}</td>
                    <td className="num ws-mono">{r.consumption === null || r.consumption === undefined || r.consumption === "" ? "—" : num(r.consumption, 3)}</td>
                    <td className="num ws-mono">{n === null ? "—" : num(n, 2)}</td>
                  </tr>);
                })}</tbody>
                {units.length > 0 && <tfoot><tr>
                  <td colSpan={5} style={{ textAlign: "right" }}><b>The whole order needs</b></td>
                  <td className="num ws-small ws-muted">total</td>
                  <td className="num ws-mono"><b>{units.map(([u, n]) => `${num(n, 2)} ${u === "—" ? "(no unit on the sheet)" : u}`).join(" · ")}</b></td>
                </tr></tfoot>}
              </table>
            </div>
            );
          })() : (
            <div className="ws-small ws-muted">No material lines yet — read them from the buyer's attachment, the ERP, or type them.</div>
          )}
        </div>
      ))}
      {!live.length && <Empty title="No styles yet" text="Add the styles the buyer asked about and their BOM follows." />}
    </Card>
  );
}

function BomEditor({ deal, styleKey, style, onClose, onSave, locked, onDeal, toast }: { deal: R; styleKey: string; style: R; onClose: () => void; onSave: (bom: R[]) => void; locked: boolean; onDeal: (d: R) => void; toast: (m: string, t?: "ok" | "bad") => void }) {
  const [rows, setRows] = useState<R[]>(() => (style.bom || []).map((r: R) => ({ ...r })));
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState<{ tone: "ok" | "warn" | "bad"; text: string } | null>(null);
  const [erp, setErp] = useState<string[]>([]);
  const [atts, setAtts] = useState<R[]>([]);
  const [paste, setPaste] = useState("");
  const [pasteOpen, setPasteOpen] = useState(false);
  const plainRef = useRef<HTMLInputElement | null>(null);
  const aiRef = useRef<HTMLInputElement | null>(null);
  const set = (i: number, k: string, v: any) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  useEffect(() => { void call("deal_bom_sources", { deal_id: deal.id }).then((r) => r.ok && setAtts(r.attachments || [])); }, [deal.id]);

  /* Every door answers {ok, deal, bom:{rows, source, warnings, erp}} - one landing point for all of them. */
  const landed = (r: R) => {
    setBusy("");
    if (!r.ok) { setNote({ tone: "bad", text: r.error || "Could not read that." }); return; }
    const st = (r.deal?.styles || []).find((s: R) => s.key === styleKey);
    setRows(((st?.bom || []) as R[]).map((x: R) => ({ ...x })));
    if (r.deal) onDeal(r.deal);
    const n = r.bom?.rows ?? 0;
    const w = (r.bom?.warnings || []) as string[];
    setErp((r.bom?.erp || []) as string[]);
    setNote({ tone: w.length ? "warn" : "ok", text: `${n} line(s) read from ${r.bom?.source || "the sheet"}.` });
    toast(`${n} BOM line(s) read from ${r.bom?.source || "the sheet"}`, "ok");
  };
  const run = (what: string, fn: string, params: R) => { setBusy(what); void call(fn, params).then(landed).catch(() => { setBusy(""); setNote({ tone: "bad", text: "Could not reach the server." }); }); };
  const upload = (f: File, ai: boolean) => {
    if (f.size > 8 * 1024 * 1024) { setNote({ tone: "bad", text: "That file is larger than 8 MB. Send the BOM sheet only." }); return; }
    const rd = new FileReader();
    const what = ai ? "ai" : "upload";
    setBusy(what);
    rd.onload = () => run(what, ai ? "deal_bom_ai" : "deal_bom_upload", { deal_id: deal.id, style_key: styleKey, filename: f.name, data: String(rd.result || "") });
    rd.onerror = () => { setBusy(""); setNote({ tone: "bad", text: "That file could not be read from disk." }); };
    rd.readAsDataURL(f);
  };

  const sources = (
    <div style={{ marginBottom: 12 }}>
      <div className="ws-row" style={{ flexWrap: "wrap", gap: 8 }}>
        <input ref={aiRef} type="file" accept=".xlsx,.xls,.xlsm,.csv,.tsv" style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f, true); e.target.value = ""; }} />
        <input ref={plainRef} type="file" accept=".xlsx,.xls,.xlsm,.csv,.tsv" style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f, false); e.target.value = ""; }} />
        <Btn sm kind="primary" busy={busy === "ai"} onClick={() => aiRef.current?.click()} title="Send the sheet to the model and take the rows it returns">
          <Sparkles size={13} /> Read it with AI
        </Btn>
        <Btn sm busy={busy === "upload"} onClick={() => plainRef.current?.click()} title="Read the sheet with the fixed column reader (fast, no model)">
          <Upload size={13} /> Read the sheet
        </Btn>
        <Btn sm busy={busy === "erp"} onClick={() => run("erp", "deal_bom_from_erp", { deal_id: deal.id, style_key: styleKey })}>
          <Database size={13} /> Read the ERP's BOM
        </Btn>
        {atts.map((a) => (
          <Btn key={a.id} sm busy={busy === `mail${a.id}`} onClick={() => run(`mail${a.id}`, "deal_bom_from_mail", { deal_id: deal.id, style_key: styleKey, attachment_id: a.id })}
            title={`Read ${a.filename} from the buyer's mail`}>{((a.filename || "attachment") as string).length > 26 ? ((a.filename || "attachment") as string).slice(0, 24) + "…" : a.filename}</Btn>))}
        <Btn sm onClick={() => setPasteOpen((v) => !v)} title="Paste JSON that a model returned anywhere">{pasteOpen ? "Hide paste box" : "Paste lines"}</Btn>
      </div>
      {!locked && <div className="ws-small ws-muted" style={{ marginTop: 6 }}>
        A buyer layout the reader does not know? “Read it with AI” sends the sheet to the model and takes back the
        rows. Both readers write to the Tech Pack as well, once the style is in the ERP.
      </div>}
      {locked && <div style={{ marginTop: 8 }}><Note>This style is in the ERP as <b>{style.tech_pack}</b>: the lines you load here go into its Tech Pack, and a draft Cost Sheet is rebuilt from it. A submitted Cost Sheet is never touched.</Note></div>}
      {pasteOpen && (
        <div style={{ marginTop: 10 }}>
          <textarea className="ws-textarea" rows={5} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder='[{"item_code":"U70","material_type":"Fabric","description":"(Self) 100% LYOCELL","uom":"Yard","consumption":1.47}]' style={{ width: "100%", fontFamily: "ui-monospace, monospace", fontSize: 12 }} />
          <div className="ws-row" style={{ marginTop: 6 }}><Btn sm busy={busy === "paste"} onClick={() => run("paste", "deal_bom_paste", { deal_id: deal.id, style_key: styleKey, rows: paste, source: "pasted lines" })}>Use these lines</Btn></div>
        </div>
      )}
    </div>
  );

  return (
    <Modal wide title={`BOM — ${style.style_no || "new style"}`} sub={style.bom_file ? `Read from ${style.bom_file}. Quantities are per garment.` : "Quantities are per garment."} onClose={onClose}
      foot={locked
        ? <><Btn onClick={onClose}>Close</Btn><Btn kind="primary" busy={busy === "apply"} onClick={() => run("apply", "deal_bom_apply", { deal_id: deal.id, style_key: styleKey })}>Send these lines to the ERP</Btn></>
        : <><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" onClick={() => onSave(rows)}>Keep these lines</Btn></>}>
      {sources}
      {note && <div style={{ marginBottom: 10 }}><Note tone={note.tone === "ok" ? undefined : note.tone}>{note.text}</Note></div>}
      {erp.length > 0 && <div style={{ marginBottom: 10 }}><Note tone="ok">{erp.join(" ")}</Note></div>}
      {style.warnings?.length > 0 && <div style={{ marginBottom: 10 }}><Note tone="warn">{style.warnings.join(" · ")}</Note></div>}
      <div className="ws-table-wrap">
        <table className="ws-table ws-table--edit">
          <thead><tr><th>Type</th><th>Buyer code</th><th>Description</th><th>Colour</th><th>UOM</th><th className="num">Per garment</th><th /></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i}>
              <td style={{ width: 130 }}><Select sm value={r.material_type} onChange={(v) => set(i, "material_type", v)} options={MATERIAL_TYPES} disabled={locked} /></td>
              <td style={{ width: 100 }}><Input sm value={r.item_code} onChange={(v) => set(i, "item_code", v)} disabled={locked} /></td>
              <td><Input sm value={r.description} onChange={(v) => set(i, "description", v)} disabled={locked} /></td>
              <td style={{ width: 100 }}><Input sm value={r.colour} onChange={(v) => set(i, "colour", v)} disabled={locked} /></td>
              <td style={{ width: 80 }}><Input sm value={r.uom} onChange={(v) => set(i, "uom", v)} disabled={locked} /></td>
              <td style={{ width: 100 }}><Input sm num type="number" value={r.consumption ?? ""} onChange={(v) => set(i, "consumption", v === "" ? null : Number(v))} disabled={locked} /></td>
              <td>{!locked && <Btn sm icon kind="plain" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 size={13} /></Btn>}</td>
            </tr>))}</tbody>
        </table>
      </div>
      {!locked && <div className="ws-mt-s"><Btn sm onClick={() => setRows([...rows, { material_type: "Trim", description: "", consumption: 1, uom: "Nos" }])}><Plus size={13} /> Add line</Btn></div>}
    </Modal>
  );
}

/* What the buyer actually sent, and what happened to each file. A mail is not "read" just because it had attachments:
   a document that is too big, a scan, or a format nothing opens used to vanish without a word. This says so, and gives
   one button to read the whole conversation again (the Tech Pack AND the BOM). */
function MailDocuments({ deal, setDeal, toast }: StepProps) {
  const [docs, setDocs] = useState<R[]>([]);
  const [busy, setBusy] = useState(false);
  const load = () => { void call("deal_documents", { deal_id: deal.id }).then((r) => r.ok && setDocs(r.documents || [])); };
  useEffect(load, [deal.id, deal.updated_at]);
  const readAll = async () => {
    setBusy(true);
    const r = await call("deal_read_documents", { deal_id: deal.id });
    setBusy(false);
    if (!r.ok) { toast(r.error || "Could not read the documents.", "bad"); return; }
    if (r.deal) setDeal(r.deal);
    load();
    const bits = [`${r.documents.length} document(s) read`];
    if (r.bom_lines) bits.push(`${r.bom_lines} BOM line(s)`);
    if ((r.spec_styles || []).length) bits.push(`tech pack read for ${r.spec_styles.join(", ")}`);
    if ((r.failed || []).length) bits.push(`could not read: ${r.failed.join("; ")}`);
    toast(bits.join(" · "), (r.failed || []).length ? "bad" : "ok");
  };
  if (!docs.length) return null;
  return (
    <Card title={<span style={{ whiteSpace: "nowrap" }}>Documents in this mail</span>} flush
      sub="The buyer's Tech Pack and BOM are two different documents; both are read, each into its own place."
      right={<Btn sm busy={busy} onClick={readAll}><RefreshCw size={13} /> Read them again</Btn>}>
      {docs.map((d: R) => (
        <div key={d.attachment_id} className="ws-list-row" style={{ cursor: "default" }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <b className="ws-small">{d.filename}</b>
            <div className="ws-small ws-muted">{d.mime} · {d.size_mb >= 1 ? `${d.size_mb} MB` : `${Math.max(1, Math.round(Number(d.size_mb) * 1024))} KB`}</div>
          </div>
          {d.parsed ? <Badge tone="ok">read</Badge> : d.readable ? <Badge tone="warn">kept, not parsed</Badge> : <Badge tone="bad">not kept</Badge>}
          {d.error ? <span className="ws-small ws-muted" style={{ maxWidth: 340 }} title={d.error}>{d.error}</span> : null}
        </div>))}
    </Card>
  );
}

/* The Tech Pack itself: a specification, not a material list. The measurement chart, the construction / cutting
   notes, wash & care and packing come from the buyer's own tech pack document - the second thing a mail carries. */
function Specification({ deal }: { deal: R }) {
  const live = (deal.styles || []).filter((s: R) => s.status !== "dropped" && s.spec);
  if (!live.length) return null;
  const ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL"];
  return (
    <Card title={<span style={{ whiteSpace: "nowrap" }}>Tech pack</span>} flush
      sub="The specification: measurement chart, construction and cutting, wash & care, packing. Not the same document as the BOM above — this is how the garment measures and how it is made."
      right={<span className="ws-small ws-muted">from the buyer&rsquo;s tech pack</span>}>
      {live.map((s: R) => {
        const spec = s.spec || {};
        const rows: R[] = spec.measurements || [];
        const sizes: string[] = [];
        for (const r of rows) for (const k of Object.keys(r.values || {})) if (!sizes.includes(k)) sizes.push(k);
        sizes.sort((a, b) => {
          const ia = ORDER.indexOf(a.toUpperCase()), ib = ORDER.indexOf(b.toUpperCase());
          return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
        });
        const has = (v: any) => v !== null && v !== undefined && v !== "" && v !== "—";
        const units = spec.measurement_uom || "cm";
        return (
          <div key={s.key} style={{ padding: "12px 16px", borderTop: "1px solid var(--ws-line, #eceff3)" }}>
            <div className="ws-row" style={{ marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
              <b className="ws-mono">{s.style_no || "New style"}</b>
              {spec.size_range ? <Badge>{spec.size_range}</Badge> : null}
              <Badge tone={rows.length ? "ok" : undefined}>{rows.length} measurement row(s)</Badge>
              {spec.source ? <span className="ws-small ws-muted">from {spec.source}</span> : null}
            </div>
            {(spec.unmapped_sizes || []).length > 0 && <div style={{ marginBottom: 8 }}><Note tone="warn">
              Sizes {spec.unmapped_sizes.join(", ")} are not columns in the ERP&rsquo;s measurement chart (XXS–XXL), so their
              values could not be charted.</Note></div>}
            {rows.length > 0 && (
              <div className="ws-table-wrap">
                <table className="ws-table">
                  <thead><tr><th>Point of measure</th><th className="num">Tol ±</th>{sizes.map((z) => <th key={z} className="num">{z}</th>)}</tr></thead>
                  <tbody>{rows.map((r: R, i: number) => (
                    <tr key={i}>
                      <td>{r.point_of_measure || r.pom_code || "—"}{r.section ? <span className="ws-small ws-muted"> · {r.section}</span> : null}</td>
                      <td className="num ws-mono">{has(r.tolerance) ? num(r.tolerance, 2) : "—"}</td>
                      {sizes.map((z) => <td key={z} className="num ws-mono">{has((r.values || {})[z]) ? num((r.values || {})[z], 2) : "—"}</td>)}
                    </tr>))}</tbody>
                </table>
                <div className="ws-small ws-muted" style={{ padding: "6px 2px" }}>All in {units}, before wash where the pack says so.</div>
              </div>
            )}
            {(spec.construction_notes || spec.wash_care || spec.packing_notes) && (
              <div className="ws-grid ws-grid--3" style={{ marginTop: 10 }}>
                {([["Construction & cutting", spec.construction_notes], ["Wash & care", spec.wash_care], ["Packing", spec.packing_notes]] as [string, string][])
                  .filter(([, v]) => v).map(([label, v]) => (
                    <div key={label} className="ws-card" style={{ padding: 12 }}>
                      <div className="ws-small ws-muted" style={{ marginBottom: 4 }}>{label}</div>
                      <div className="ws-small" style={{ whiteSpace: "pre-wrap" }}>{v}</div>
                    </div>))}
              </div>
            )}
          </div>);
      })}
    </Card>
  );
}

/* ───────────────────────── 2 · costing ───────────────────────── */
function CostingStep({ deal, erp, setDeal, reload, toast, go }: StepProps & { reload: () => void; erp: R; go: (p: string) => void }) {
  if (!deal.refs?.opportunity) return <Card title="Costing"><Note>Send the inquiry to the ERP first (step 1). It makes the Tech Pack each costing starts from.</Note></Card>;
  const styles = deal.styles.filter((s: R) => s.status !== "dropped");
  return (
    <>
      <Card title={<span style={{ whiteSpace: "nowrap" }}>Cost each style</span>} sub="Opens in the Costing page, on the ERP's own cost sheet - already filled from the standard costing - with the detailed sheet beside it." flush
        right={<ErpBtn label={erpPage(erp, "costing").label} url={erpPage(erp, "costing").url} />}>
        <div className="ws-table-wrap">
          <table className="ws-table">
            <thead><tr><th>Style</th><th className="num">Qty</th><th>Cost sheet</th><th className="num">Computed</th><th className="num">Quoted</th><th className="num">Margin</th><th>Status</th><th /></tr></thead>
            <tbody>{styles.map((s: R) => {
              const c = s.cost || {};
              return (
                <tr key={s.key} className="is-click" onClick={() => go(`costing/${deal.id}/${encodeURIComponent(s.key)}`)}>
                  <td><b>{s.style_no}</b><div className="ws-small ws-muted">{s.style_name}</div></td>
                  <td className="num">{num(s.qty)}</td>
                  <td className="ws-small">{s.cost_sheet || <span className="ws-muted">not started</span>}</td>
                  <td className="num">{c.computed_price ? money(c.computed_price, deal.currency, 3) : "—"}</td>
                  <td className="num"><b>{c.quoted_price ? money(c.quoted_price, deal.currency) : "—"}</b></td>
                  <td className="num">{c.margin_pct !== undefined && c.margin_pct !== null ? <span style={{ color: c.below_floor ? "var(--ws-bad)" : undefined }}>{num(c.margin_pct, 1)}%</span> : "—"}</td>
                  <td>{s.cost_status === "submitted" ? <Badge tone="ok">Submitted</Badge> : s.cost_sheet ? <Badge tone="warn">Draft</Badge> : <Badge>To do</Badge>}</td>
                  <td className="ws-nowrap">
                    <Btn sm kind={s.cost_status === "submitted" ? "ghost" : "primary"}><Calculator size={13} /> {s.cost_status === "submitted" ? "View" : s.cost_sheet ? "Continue" : "Start"}</Btn>
                    {s.cost_sheet && <span onClick={(e) => e.stopPropagation()} style={{ marginLeft: 6, display: "inline-block" }}>
                      <ErpBtn label="ERP" url={(erp[`cost_sheet:${s.cost_sheet}`] || {}).url} />
                    </span>}
                  </td>
                </tr>);
            })}</tbody>
          </table>
        </div>
      </Card>
      {styles.every((s: R) => s.cost_status === "submitted") && <Note tone="ok">Every style is costed. Next: send the quote (step 3).</Note>}
    </>
  );
}

/* ───────────────────────── 3 · quote ───────────────────────── */
function QuoteStep({ deal, setDeal, toast }: StepProps) {
  const [d, setD] = useState<R | null>(null);
  const [err, setErr] = useState("");
  const [body, setBody] = useState("");
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    (async () => {
      const r = await call("deal_quote_draft", { deal_id: deal.id });
      if (!r.ok) { setErr(r.error || ""); return; }
      setD(r); setBody(r.body); setTo(r.to || "");
    })();
  }, [deal.id]);
  const send = async () => {
    setBusy(true);
    const r = await call("deal_quote_send", { deal_id: deal.id, body, to, cc });
    setBusy(false);
    if (!r.ok) { toast(r.error || "Not sent.", "bad"); return; }
    setDeal(r.deal); toast(`Quote sent to ${r.sent.to} in the buyer's thread. Their reply will show on this deal.`);
  };
  if (err) return <Card title="Quote"><Note>{err}</Note></Card>;
  if (!d) return <Card title="Quote"><Loading rows={3} /></Card>;
  return (
    <>
      {deal.quote_sent_at && <Note tone="ok">Quote sent {when(deal.quote_sent_at)}. You can send a revised one; it goes into the same thread.</Note>}
      <Card title="Prices" flush>
        <table className="ws-table"><thead><tr><th>Style</th><th className="num">Qty</th><th className="num">Price / pc</th><th className="num">Line value</th></tr></thead>
          <tbody>{d.styles.map((s: R) => <tr key={s.key}><td><b>{s.style_no}</b></td><td className="num">{num(s.qty)}</td><td className="num">{money(s.price, deal.currency)}</td><td className="num">{money(Number(s.price || 0) * Number(s.qty || 0), deal.currency, 0)}</td></tr>)}</tbody>
        </table>
      </Card>
      <Card title="The quote mail" sub={deal.thread_key ? "Sent as a reply in the buyer's conversation, so their answer comes back here." : "This deal has no conversation yet; this mail starts one."}>
        <div style={{ display: "grid", gap: 10 }}>
          <div className="ws-form" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Field label="To"><Input value={to} onChange={setTo} /></Field>
            <Field label="Cc"><Input value={cc} onChange={setCc} placeholder="optional" /></Field>
          </div>
          <Textarea rows={14} value={body} onChange={setBody} />
          <div className="ws-row" style={{ justifyContent: "flex-end" }}><Btn kind="primary" busy={busy} disabled={!body.trim() || !to.includes("@")} onClick={send}><Send size={14} /> {deal.quote_sent_at ? "Send revised quote" : "Send the quote"}</Btn></div>
        </div>
      </Card>
    </>
  );
}

/* ───────────────────────── 4 · buyer's answer ───────────────────────── */
function ReplyStep({ deal, setDeal, toast, go }: StepProps & { go: (p: string) => void }) {
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [lost, setLost] = useState(false);
  const [reason, setReason] = useState("");
  if (!deal.refs?.price_negotiation) return <Card title="Buyer's answer"><Note>Send the quote first; the negotiation starts with it.</Note></Card>;
  const styles = deal.styles.filter((s: R) => s.status !== "dropped");
  const att = deal.attention;
  const record = async (outcome: string) => {
    setBusy(outcome);
    const body: R = { deal_id: deal.id, outcome, note, prices: Object.fromEntries(Object.entries(prices).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])) };
    if (outcome === "lost") body.lost_reason = reason;
    const r = await call("deal_record_reply", body);
    setBusy("");
    if (!r.ok) { toast(r.error || "Not recorded.", "bad"); return; }
    setDeal(r.deal); setPrices({}); setNote(""); setLost(false);
    toast(outcome === "accepted" ? "Agreed. Recorded in the ERP's price negotiation." : outcome === "lost" ? "Marked lost." : "Recorded in the ERP's price negotiation.");
  };
  const fillDetected = () => {
    const ps: number[] = att?.prices || [];
    if (!ps.length) return;
    const n: Record<string, string> = {};
    styles.forEach((s: R, i: number) => { if (ps[i] !== undefined) n[s.key] = String(ps[i]); });
    setPrices(n);
  };
  return (
    <>
      {att?.kind === "buyer_replied" && (
        <div className="ws-card" style={{ padding: 14, borderColor: "#fcd34d", background: "#fffbeb" }}>
          <div className="ws-row"><MessageSquare size={16} color="var(--ws-warn)" /><b>The buyer replied {when(att.at)}</b><Badge tone={att.intent === "accept" || att.intent === "po" ? "ok" : att.intent === "counter" ? "violet" : undefined}>{att.intent}</Badge></div>
          <div className="ws-small ws-mt-s">{att.text}</div>
          <div className="ws-row ws-mt-s">
            {deal.thread_key && <Btn sm onClick={() => go(`inbox/${encodeURIComponent(deal.thread_key)}`)}><Mail size={13} /> Read it in the conversation</Btn>}
            {att.prices?.length > 0 && <Btn sm onClick={fillDetected}>Use the prices they mention</Btn>}
          </div>
        </div>
      )}
      <Card title="Prices per style" sub="Type the buyer's counter or the agreed price, then record it. Every entry is a round in the ERP's Price Negotiation." flush>
        <div className="ws-table-wrap">
          <table className="ws-table ws-table--edit">
            <thead><tr><th>Style</th><th className="num">Qty</th><th className="num">Our offer</th><th className="num">Buyer's last</th><th className="num">Agreed</th><th style={{ width: 140 }}>Price now</th></tr></thead>
            <tbody>{styles.map((s: R) => (
              <tr key={s.key}>
                <td style={{ padding: "8px 12px" }}><b>{s.style_no}</b>{s.status === "agreed" && <> <Badge tone="ok">Agreed</Badge></>}</td>
                <td className="num">{num(s.qty)}</td>
                <td className="num">{money(s.offer_price, deal.currency)}</td>
                <td className="num">{s.buyer_price ? money(s.buyer_price, deal.currency) : "—"}</td>
                <td className="num">{s.agreed_price ? <b>{money(s.agreed_price, deal.currency)}</b> : "—"}</td>
                <td><Input sm num type="number" value={prices[s.key] ?? ""} onChange={(v) => setPrices({ ...prices, [s.key]: v })} placeholder={s.buyer_price ? String(s.buyer_price) : String(s.offer_price ?? "")} aria-label={`Price for ${s.style_no}`} /></td>
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
      <Card title="Record the answer">
        <Field label="Note (optional)"><Input value={note} onChange={setNote} placeholder="e.g. agreed on the call with Jane" /></Field>
        <div className="ws-row ws-mt">
          <Btn kind="primary" busy={busy === "accepted"} onClick={() => record("accepted")}><Check size={14} /> Agreed {Object.values(prices).some(Boolean) ? "at these prices" : "at our offer"}</Btn>
          <Btn busy={busy === "counter"} disabled={!Object.values(prices).some(Boolean)} onClick={() => record("counter")}>Buyer countered</Btn>
          <Btn busy={busy === "our_counter"} disabled={!Object.values(prices).some(Boolean)} onClick={() => record("our_counter")}>We counter</Btn>
          <Btn kind="danger" onClick={() => setLost(true)}>Lost</Btn>
        </div>
        <div className="ws-small ws-muted ws-mt-s">“Agreed” with no price typed uses the buyer's last price, else our offer. To reply in words, use the conversation.</div>
      </Card>
      {lost && <Modal title="Mark this deal lost" onClose={() => setLost(false)} foot={<><Btn onClick={() => setLost(false)}>Cancel</Btn><Btn kind="danger" busy={busy === "lost"} onClick={() => record("lost")}>Mark lost</Btn></>}>
        <Field label="Why?"><Input value={reason} onChange={setReason} placeholder="e.g. price too high, went to another factory" autoFocus /></Field>
      </Modal>}
    </>
  );
}

/* ───────────────────────── 5 · contract ───────────────────────── */
/* The contract form is not a list of inputs typed in this file: it is the ERP's own Sales Contract field list, fetched by
   `deal_contract_form` (label, type, section, the Select choices, and the records that exist for a Link like Incoterm). */
type CField = { name: string; label: string; type: string; reqd: boolean; section: string; options: string[]; link?: string | null };

/** The trade term, checked against the contract's own freight / insurance / mode lines as you change it.

    The eleven Incoterms are not interchangeable words: each one fixes who pays the freight, who insures, who clears
    import and where the risk passes. The ERP only checks that the value is one of its records — it cannot know that
    "FOB" was picked for an air shipment, or that the contract says the buyer pays freight while DAP says we do. So
    the mismatch is named here, while the person can still change it, instead of at the forwarder six weeks later. */
function termNotes(d: R, help: R[]): { tone: "bad" | "warn" | ""; text: string }[] {
  const code = String(d?.incoterm || "").toUpperCase();
  if (!code) return [{ tone: "bad", text: "No Incoterm yet — the ERP will not sign the contract without one." }];
  const t = (help || []).find((x: R) => x.code === code);
  if (!t) return [{ tone: "bad", text: `"${code}" is not one of the eleven trade terms in the ERP.` }];
  const out: { tone: "bad" | "warn" | ""; text: string }[] = [];
  const mode = String(d?.shipment_mode || "").toLowerCase();
  if (mode.includes("air") && t.modes === "sea")
    out.push({ tone: "bad", text: `${code} is a sea term and this shipment is by air — for air use FCA (buyer's freight), CPT/CIP (our freight), DAP or DDP.` });
  const fr = String(d?.freight_by || "").trim();
  if (fr && fr.toLowerCase() !== String(t.freight).toLowerCase())
    out.push({ tone: "warn", text: `${code} puts the freight with the ${String(t.freight).toLowerCase()}, but the contract says ${fr.toLowerCase()} — the forwarder will bill the wrong party.` });
  const ins = String(d?.insurance_by || "").trim();
  if (!ins) out.push({ tone: "warn", text: `${code} puts insurance with the ${String(t.insurance).toLowerCase()}, and the insurance line is blank — an uninsured loss in transit is then ours.` });
  else if (ins.toLowerCase() !== String(t.insurance).toLowerCase())
    out.push({ tone: "warn", text: `${code} puts insurance with the ${String(t.insurance).toLowerCase()}, the contract says ${ins.toLowerCase()} — allowed only if the buyer agreed it in writing.` });
  if (!String(d?.named_place || "").trim())
    out.push({ tone: "bad", text: `${code} needs a named place — the town or warehouse the term points at.` });
  return out;
}

function ContractStep({ deal, erp, setDeal, toast }: StepProps & { erp: R }) {
  const [draft, setDraft] = useState<R | null>(deal.contract_draft || null);
  const [ready, setReady] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [dirty, setDirty] = useState(false);
  const [fields, setFields] = useState<CField[]>([]);
  const [options, setOptions] = useState<R>({});
  const [ihelp, setIhelp] = useState<R[]>([]);
  const [dnotes, setDnotes] = useState<R[]>([]);
  const [notice, setNotice] = useState("");
  const signed = !!draft?._signed;
  const agreed = deal.styles.filter((s: R) => s.status !== "dropped").every((s: R) => s.status === "agreed");
  useEffect(() => { setDraft(deal.contract_draft || null); }, [deal.contract_draft]);
  /* the form is the ERP's field list, so a Select offers the ERP's choices and a Link offers the records that exist */
  useEffect(() => {
    void call("deal_contract_form", { deal_id: deal.id }).then((r) => {
      if (!r.ok) return;
      setFields(r.fields || []); setOptions(r.options || {}); setIhelp(r.incoterm_help || []);
      setDnotes(r.date_notes || []); setNotice(r.notice || "");
      if (!deal.contract_draft && r.draft && Object.keys(r.draft).length) setDraft(r.draft);
      if ((r.readiness || []).length) setReady(r.readiness);
    });
  }, [deal.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const prepare = async () => {
    setBusy("prepare");
    const r = await call("deal_contract_prepare", { deal_id: deal.id });
    setBusy("");
    if (!r.ok) { toast(r.error || "Could not prepare the contract.", "bad"); return; }
    setDraft(r.draft); setReady(r.readiness); setDeal(r.deal);
    toast(`Quotation ${r.deal.refs.quotation} submitted; the contract draft is ready to complete.`);
  };
  const reloadErp = async () => {
    setBusy("reload");
    const r = await call("deal_contract_form", { deal_id: deal.id, refresh: true });
    setBusy("");
    if (!r.ok) { toast(r.error || "Could not read the contract from the ERP.", "bad"); return; }
    if (r.draft) setDraft(r.draft);
    setReady(r.readiness || []); setDirty(false); setNotice(r.notice || "");
    toast("Reloaded from the ERP - what you see is what the Sales Contract holds.");
  };
  const saveDraft = async (): Promise<boolean> => {
    if (!draft) return false;
    setBusy("save");
    const r = await call("deal_contract_update", { deal_id: deal.id, draft });
    setBusy("");
    if (!r.ok) { toast(r.error || "Not saved.", "bad"); return false; }
    setDraft(r.draft); setReady(r.readiness || []); setDirty(false); return true;
  };
  const create = async (sign: boolean) => {
    if (dirty && !(await saveDraft())) return;
    setBusy(sign ? "sign" : "create");
    const r = await call("deal_contract_create", { deal_id: deal.id, sign });
    setBusy("");
    if (!r.ok) { toast(r.error || "The ERP refused it.", "bad"); return; }
    setDeal(r.deal); toast(sign ? `Contract ${r.deal.refs.sales_contract} signed. Next: the Sales Order.` : `Contract ${r.deal.refs.sales_contract} saved as a draft in the ERP.`);
  };
  if (!agreed) return <Card title="Contract"><Note>Record the agreed price for every style first (step 4).</Note></Card>;
  if (!draft) return (
    <Card title="Contract">
      <p className="ws-small" style={{ marginTop: 0 }}>This makes the ERP Quotation at the agreed prices and submits it, then builds the Sales Contract draft from it: one line per style and colour, sizes from the Tech Pack, dates from the inquiry, terms from the buyer's last contract.</p>
      <Btn kind="primary" busy={busy === "prepare"} onClick={prepare}><FileSignature size={14} /> Prepare the contract</Btn>
    </Card>
  );
  const setH = (k: string, v: any) => { setDirty(true); setDraft({ ...draft, [k]: v }); };
  const sections: { title: string; items: CField[] }[] = [];
  for (const f of fields) {
    const title = f.section || "Terms";
    let g = sections.find((x) => x.title === title);
    if (!g) { g = { title, items: [] }; sections.push(g); }
    g.items.push(f);
  }
  const setItem = (i: number, k: string, v: any) => { setDirty(true); setDraft({ ...draft, items: draft.items.map((it: R, j: number) => (j === i ? { ...it, [k]: v } : it)) }); };
  const setSize = (i: number, v: any) => { setDirty(true); setDraft({ ...draft, sizes: draft.sizes.map((z: R, j: number) => (j === i ? { ...z, qty: v } : z)) }); };
  return (
    <>
      {(deal.refs?.sales_contract || fields.length > 0) && <div className="ws-row" style={{ justifyContent: "flex-end", marginBottom: 2 }}>
        <span className="ws-small ws-muted" style={{ marginRight: "auto" }}>Every field below is written to the Sales Contract in the ERP.</span>
        {deal.refs?.sales_contract && <Btn sm kind="plain" busy={busy === "reload"} onClick={reloadErp}
          title="Read the Sales Contract from the ERP, so a change made there shows up here">Reload from the ERP</Btn>}
      </div>}
      {notice && <Note tone="warn">{notice}</Note>}
      {/* signed, but the ERP's own after-submit script could not write a field it forbids after submission: said out loud,
          because a silent gap here is what makes a contract look wrong in the ERP later */}
      {draft?._sign_warning && <Note tone="warn"><b>Signed, with one thing the ERP would not store:</b> {draft._sign_warning}</Note>}
      {signed ? <Note tone="ok">Contract {deal.refs.sales_contract} is signed. Changes now go through an amendment in the ERP.</Note>
        : ready.length ? <Note tone="warn"><b>Before it can be signed:</b> {ready.join(" · ")}</Note>
        : <Note tone="ok">Everything the ERP checks at signing is filled in.</Note>}
      {/* the ERP's checks and the contract's own arithmetic are two different things: these are the dates and the term,
          read against each other, and they are what a late shipment is actually made of */}
      {dnotes.map((n: R, i: number) => <Note key={i} tone={n.tone === "bad" ? "bad" : n.tone === "warn" ? "warn" : undefined}><b>{n.title}</b> — {n.sub}</Note>)}
      {sections.map((g) => (
        <div key={g.title}>
          <Card title={g.title || "Terms"} sub="The ERP's own fields and choices">
            <div className="ws-form">
              {g.items.map((f) => <ContractField key={f.name} f={f} value={draft[f.name]} options={options[f.name]} signed={signed} onChange={(v) => setH(f.name, v)} />)}
            </div>
          </Card>
          {/ship|incoterm/i.test(g.title) && <TermCard draft={draft} help={ihelp} />}
        </div>))}
      <Card title="Lines" flush>
        <div className="ws-table-wrap">
          <table className="ws-table ws-table--edit">
            <thead><tr><th>Style</th><th>Colour</th><th className="num">Qty</th><th className="num">Price</th><th>Ex-factory</th><th>ETD</th><th>In-warehouse</th><th>Buyer PO</th></tr></thead>
            <tbody>{(draft.items || []).map((it: R, i: number) => (
              <tr key={i}>
                <td style={{ padding: "8px 10px" }} className="ws-nowrap"><b>{it.style_no}</b></td>
                <td style={{ minWidth: 140 }}><Input sm value={it.colour} onChange={(v) => setItem(i, "colour", v)} disabled={signed} /></td>
                <td style={{ minWidth: 80 }}><Input sm num type="number" value={it.qty ?? ""} onChange={(v) => setItem(i, "qty", Number(v))} disabled={signed} /></td>
                <td className="num ws-nowrap">{money(it.rate, deal.currency)}</td>
                <td style={{ width: 140 }}><Input sm type="date" value={String(it.ex_factory_date || "").slice(0, 10)} onChange={(v) => setItem(i, "ex_factory_date", v)} disabled={signed} /></td>
                <td style={{ width: 140 }}><Input sm type="date" value={String(it.etd || "").slice(0, 10)} onChange={(v) => setItem(i, "etd", v)} disabled={signed} /></td>
                <td style={{ width: 140 }}><Input sm type="date" value={String(it.in_warehouse_date || "").slice(0, 10)} onChange={(v) => setItem(i, "in_warehouse_date", v)} disabled={signed} /></td>
                <td style={{ width: 110 }}><Input sm value={it.buyer_po_code || ""} onChange={(v) => setItem(i, "buyer_po_code", v)} disabled={signed} /></td>
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
      <Card title="Size breakdown" sub="Must add up to each line's quantity." flush>
        {(draft.sizes || []).length === 0 ? <div style={{ padding: 16 }}><Note tone="warn">The Tech Pack lists no sizes, so there are no size rows. Add the sizes on the Tech Pack (Records → Tech Pack) or on the contract in the ERP.</Note></div> : (
          <div className="ws-table-wrap">
            <table className="ws-table ws-table--edit">
              <thead><tr><th>Style / colour</th><th>Size</th><th style={{ width: 120 }}>Qty</th></tr></thead>
              <tbody>{draft.sizes.map((z: R, i: number) => (
                <tr key={i}><td style={{ padding: "6px 10px" }} className="ws-small">{(draft.items.find((it: R) => it.style_item === z.style_item && (it.colour || "") === (z.colour || ""))?.style_no
                  || draft.items.find((it: R) => it.style_item === z.style_item)?.style_no) || z.style_item} · {z.colour || "—"}</td><td><b>{z.size}</b></td>
                  <td><Input sm num type="number" value={z.qty ?? 0} onChange={(v) => setSize(i, Number(v))} disabled={signed} /></td></tr>))}</tbody>
            </table>
          </div>)}
      </Card>
      {!signed && <div className="ws-row" style={{ justifyContent: "flex-end" }}>
        {dirty && <span className="ws-small ws-muted">Unsaved changes</span>}
        <Btn busy={busy === "save"} disabled={!dirty} onClick={saveDraft}>Save</Btn>
        <Btn kind="dark" busy={busy === "create"} onClick={() => create(false)}>Save to the ERP (draft)</Btn>
        <Btn kind="primary" busy={busy === "sign"} disabled={ready.length > 0 && !dirty} onClick={() => create(true)}><FileSignature size={14} /> Sign the contract</Btn>
        {/* signing is a decision, and the ERP is always allowed to make it: the tower can be told no by the site's own
            scripts (a field it will not let anyone change after submission), the ERP never can */}
        <ErpBtn url={erp.sales_contract?.url} label="Sign / approve in the ERP" />
      </div>}
    </>
  );
}

/* ───────────────────────── the trade term, explained ─────────────────────────
   The Incoterm is the one field on this page nobody can be expected to know by heart, and the ERP asks for it before it
   will sign. So it is explained where it is chosen: what the term obliges, who pays what, and what does not add up in
   this contract. Choosing DAP is one click either way - the difference is knowing that DAP means we carry the risk to
   the buyer's door and the buyer pays the US import duty. */
function TermCard({ draft, help }: { draft: R; help: R[] }) {
  const code = String(draft?.incoterm || "").toUpperCase();
  const t = (help || []).find((x: R) => x.code === code);
  const notes = termNotes(draft, help);
  if (!(help || []).length) return null;
  return (
    <Card title={`Trade term${code ? ` — ${code}` : ""}`} sub="What the Incoterm obliges us to do">
      {t ? (
        <p className="ws-small" style={{ marginTop: 0 }}><b>{t.name}.</b> {t.meaning}</p>
      ) : (
        <Note tone="warn">Choose the trade term from the dropdown above — it is the one field the buyer will check first, because it fixes who pays the freight, insurance and import duty.</Note>
      )}
      {t && <dl className="ws-kv">
        <dt>Risk passes</dt><dd>{t.risk}</dd>
        <dt>Freight paid by</dt><dd>{t.freight}</dd>
        <dt>Insurance paid by</dt><dd>{t.insurance}</dd>
        <dt>Import duty paid by</dt><dd>{t.duty}</dd>
        <dt>Typical use</dt><dd>{t.use_when}</dd>
      </dl>}
      {notes.map((n, i) => <Note key={i} tone={n.tone || undefined}>{n.text}</Note>)}
      <details style={{ marginTop: 8 }}>
        <summary className="ws-small">All eleven terms, in plain words</summary>
        <div className="ws-table-wrap" style={{ marginTop: 8 }}>
          <table className="ws-table">
            <thead><tr><th>Term</th><th>Means</th><th>Risk passes</th><th>Freight</th><th>Insurance</th><th>Duty</th><th>Mode</th></tr></thead>
            <tbody>{help.map((x: R) => (
              <tr key={x.code} style={x.code === code ? { background: "var(--ws-tint, #f4f6fb)" } : undefined}>
                <td className="ws-nowrap"><b>{x.code}</b></td><td className="ws-small">{x.meaning}</td>
                <td className="ws-small">{x.risk}</td><td className="ws-small">{x.freight}</td>
                <td className="ws-small">{x.insurance}</td><td className="ws-small">{x.duty}</td>
                <td className="ws-small">{x.modes === "sea" ? "sea only" : "air or sea"}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}

/** One contract field, drawn the way the ERP says it is: a Select for a Select, a picker of real records for a Link,
    a date for a date. Nothing here decides what is valid - the ERP's own list does. */
function ContractField({ f, value, options, signed, onChange }: {
  f: CField; value: any; options?: string[]; signed: boolean; onChange: (v: any) => void;
}) {
  const isLink = !!f.link;
  const choices = (isLink ? (options || []) : (f.options || [])).filter((x) => x !== "");
  const label = f.label + (f.reqd ? " *" : "");
  if (isLink || f.type === "Select") {
    /* a value typed before the form knew better (an Incoterm called "cortex") stays visible, marked, instead of silently
       turning into an empty box - and saving it gives the reason plus the values the ERP has */
    const stale = value && !choices.includes(String(value));
    return <Field label={label}
      hint={isLink ? (choices.length ? `a record in the ERP (${f.link})` : `The ERP has no ${f.link} records yet - add one there first`) : undefined}>
      <Select value={value ?? ""} onChange={(v) => onChange(v)} placeholder={f.reqd ? "Choose…" : "—"}
        options={[...(stale ? [{ v: String(value), l: `${value} - not in the ERP` }] : []), ...choices.map((c) => ({ v: c, l: c }))]}
        disabled={signed} />
    </Field>;
  }
  if (f.type === "Date") return <Field label={label}><Input type="date" value={String(value || "").slice(0, 10)} onChange={(v) => onChange(v)} disabled={signed} /></Field>;
  if (["Int", "Float", "Currency", "Percent"].includes(f.type)) return <Field label={label}><Input num type="number" value={value ?? ""} onChange={(v) => onChange(v === "" ? null : Number(v))} disabled={signed} /></Field>;
  if (f.type === "Small Text" || f.type === "Text" || f.type === "Text Editor" || f.type === "Long Text") {
    return <Field label={label} wide><Textarea rows={2} value={value ?? ""} onChange={(v) => onChange(v)} /></Field>;
  }
  return <Field label={label}><Input value={value ?? ""} onChange={(v) => onChange(v)} disabled={signed} /></Field>;
}

/* ───────────────────────── 6 · order ───────────────────────── */
function OrderStep({ deal, erp, setDeal, toast, go, reload }: StepProps & { erp: R; go: (p: string) => void; reload: () => void }) {
  const cx = useCx();
  const [busy, setBusy] = useState(false);
  const so = deal.refs?.sales_order;
  const signed = !!deal.contract_draft?._signed;
  const make = async () => {
    setBusy(true);
    const r = await call("deal_make_order", { deal_id: deal.id });
    setBusy(false);
    if (!r.ok) { toast(r.error || "The ERP refused it.", "bad"); return; }
    setDeal(r.deal); toast(`Sales Order ${r.deal.refs.sales_order} created as a draft.`);
    reload();
  };
  if (!signed) return <Card title="Sales order"><Note>Sign the contract first (step 5).</Note></Card>;
  if (!so) return (
    <Card title="Sales order">
      <p className="ws-small" style={{ marginTop: 0 }}>The ERP makes one Sales Order row per colour and size from the signed contract, with the contract prices, PO and dates. It is saved as a draft for you to check and submit.</p>
      <Btn kind="primary" busy={busy} onClick={make}><ShoppingBag size={14} /> Make the Sales Order</Btn>
    </Card>
  );
  const s = erp.sales_order || {};
  const f = erp.follow_on || {};
  const FOLLOW: [string, string][] = [["Order TNA", "T&A plan"], ["Production Card", "Production cards"], ["Fabric Requisition", "Fabric requisitions"], ["Packing List", "Packing lists"], ["Sales Invoice", "Invoices"]];
  return (
    <>
      <OpenOrder so={so} go={go} />
      <Card title={`Sales Order ${so}`} right={<>
        <ErpBtn url={s.url} label="Submit / approve in the ERP" />
        <Btn sm onClick={() => cx?.openDoc?.("Sales Order", so)}><ExternalLink size={13} /> Open</Btn></>}>
        <dl className="ws-kv">
          <dt>Status</dt><dd>{Number(s.docstatus) === 2 ? "Cancelled" : s.status || (Number(s.docstatus) === 0 ? "Draft" : "—")}
            {Number(s.docstatus) === 0 && <span className="ws-small ws-muted"> — submitting is the ERP's own approval: press “Submit / approve in the ERP” when you are ready to plan production</span>}
            {Number(s.docstatus) === 2 && <span className="ws-small ws-muted"> — cancelled in the ERP; make an amendment there (the tower follows it automatically)</span>}</dd>
          <dt>Value</dt><dd>{money(s.grand_total, deal.currency)}</dd>
          <dt>Delivery</dt><dd>{day(s.delivery_date)}</dd>
          <dt>Delivered / billed</dt><dd>{num(s.per_delivered, 0)}% / {num(s.per_billed, 0)}%</dd>
        </dl>
      </Card>
      <Card title="After the order" sub="What the ERP has made from this order so far.">
        <div className="ws-grid ws-grid--3">
          {FOLLOW.map(([dt, l]) => <div key={dt} className="ws-card" style={{ padding: 12 }}><div className="ws-small ws-muted">{l}</div><div className="ws-kpi__value" style={{ fontSize: 20 }}>{f[dt] === null || f[dt] === undefined ? "—" : f[dt]}</div></div>)}
        </div>
        <div className="ws-row ws-mt"><Btn onClick={() => go("tna")}>T&A calendar</Btn><Btn onClick={() => go("orders")}>Orders</Btn></div>
      </Card>
    </>
  );
}

/** Once the Sales Order exists the deal hands over to the Order page: the order's step chips and one button. */
function OpenOrder({ so, go, label = "Open the order", step }: { so: string; go: (p: string) => void; label?: string; step?: string }) {
  const r = useCall("order_get", { sales_order: so }, []);
  const steps: R[] = r.data?.steps || [];
  return (
    <Card title="The order" sub="Planning, materials, production, shipping and invoicing are followed on the Order page."
      right={<Btn kind="primary" sm onClick={() => go(`orders/${encodeURIComponent(so)}${step ? "/" + step : ""}`)}><ArrowRight size={13} /> {label}</Btn>}>
      {r.loading && !r.data ? <Loading rows={1} /> : steps.length === 0 ? <div className="ws-small ws-muted">{r.error || "No step information yet."}</div> : (
        <div className="ws-stepchips">{steps.map((st) => <span key={st.key} className={`ws-stepchip is-${st.state}`} title={`${st.label}: ${st.state}`}>{st.label.split(" ")[0].replace(",", "")}</span>)}</div>)}
    </Card>
  );
}

/* ───────────────────────── side: ERP documents + timeline ───────────────────────── */
function SidePanel({ deal, erp }: { deal: R; erp: R }) {
  const cx = useCx();
  const docs: [string, string, ReactNode?, string?][] = [];
  const refs = deal.refs || {};
  const st = (docstatus: any) => (Number(docstatus) === 1 ? "submitted" : Number(docstatus) === 2 ? "cancelled" : "draft");
  if (refs.opportunity) docs.push(["Opportunity", refs.opportunity, erp.opportunity?.status, erp.opportunity?.url]);
  for (const s of deal.styles) {
    if (s.tech_pack) docs.push(["Tech Pack", s.tech_pack, st((erp[`tech_pack:${s.tech_pack}`] || {}).docstatus), (erp[`tech_pack:${s.tech_pack}`] || {}).url]);
    if (s.cost_sheet) docs.push(["Cost Sheet", s.cost_sheet, st((erp[`cost_sheet:${s.cost_sheet}`] || {}).docstatus), (erp[`cost_sheet:${s.cost_sheet}`] || {}).url]);
  }
  if (refs.price_negotiation) docs.push(["Price Negotiation", refs.price_negotiation, erp.price_negotiation?.status, erp.price_negotiation?.url]);
  if (refs.quotation) docs.push(["Quotation", refs.quotation, erp.quotation?.status, erp.quotation?.url]);
  if (refs.sales_contract) docs.push(["Sales Contract", refs.sales_contract, erp.sales_contract?.status, erp.sales_contract?.url]);
  if (refs.sales_order) docs.push(["Sales Order", refs.sales_order, erp.sales_order?.status, erp.sales_order?.url]);
  const events: R[] = [...(deal.events || [])].reverse();
  return (
    <div className="ws-stack">
      <Card title="In the ERP" flush right={<ErpBtn label={erpPage(erp).short} url={erpPage(erp).url} />}>
        {docs.length === 0 ? <div className="ws-small ws-muted" style={{ padding: 14 }}>Nothing yet. Step 1 sends the inquiry.</div> : docs.map(([dt, name, extra, url]) => (
          <div key={dt + name} className="ws-list-row" onClick={() => cx?.openDoc?.(dt, name)}>
            <div style={{ minWidth: 0, flex: 1 }}><div className="ws-small ws-muted">{dt}</div><b className="ws-small">{name}</b></div>
            {extra && <span className="ws-small ws-muted">{extra}</span>}
            {url && <span title={`Confirm ${name} in the ERP`} onClick={(e) => { e.stopPropagation(); window.open(url, "_blank", "noopener"); }}
              style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer", color: "var(--ws-accent, #2563eb)" }}>
              <span className="ws-small">ERP</span><ExternalLink size={13} />
            </span>}
          </div>))}
        {docs.length > 0 && <div className="ws-small ws-muted" style={{ padding: "8px 14px 12px" }}>Click a row to read the document here. The <b>ERP</b> link opens it in the ERP, where it is confirmed or submitted.</div>}
      </Card>
      <Card title="Buyer">
        <dl className="ws-kv"><dt>Customer</dt><dd>{deal.customer_name || "—"}</dd><dt>Contact</dt><dd>{deal.contact_name || "—"}</dd><dt>E-mail</dt><dd>{deal.contact_email || "—"}</dd>
          <dt>Terms</dt><dd>{[deal.incoterm, deal.destination].filter(Boolean).join(" ") || "—"}</dd><dt>Ex-factory</dt><dd>{day(deal.ex_factory)}</dd></dl>
      </Card>
      <Card title="Timeline">
        <div className="ws-timeline">{events.length === 0 ? <div className="ws-small ws-muted">No activity yet.</div> : events.slice(0, 40).map((e, i) => (
          <div key={i} className={`ws-tl is-${e.kind}`}><i /><div><div>{e.text}</div><div className="ws-muted">{when(e.at)}{e.by ? ` · ${e.by}` : ""}</div></div></div>))}</div>
      </Card>
    </div>
  );
}
