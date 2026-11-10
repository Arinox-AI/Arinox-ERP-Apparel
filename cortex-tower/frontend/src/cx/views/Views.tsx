import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, BarChart3, Calendar, CheckCircle2, ClipboardCheck, Database, Download, ExternalLink, FileText, Inbox, Mail, RefreshCw, Search, Shield, Sparkles, Timer, Workflow } from "lucide-react";
import { ago, call, fmtVal, slugTitle } from "../api";
import type { R } from "../api";
import { Act, Btn, Cell, Empty, Foot, List, ListSkel, Note, PageHead, Panel, Pill, Section, Seg, Sheet, Skel, Stat, Switch, Title, useCx } from "../ui";
import { tone } from "./Docs";

const greet = () => { const h = new Date().getHours(); return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };

/* ── Today — the command centre home ───────────────────────────────────── */
const FLOW = [
  { key: "intake", title: "Read the mail", hint: "POs & enquiries, read for you", icon: <Mail size={16} /> },
  { key: "intake", title: "Check & approve", hint: "edit any value, then confirm", icon: <ClipboardCheck size={16} /> },
  { key: "tna", title: "Plan the order", hint: "T&A calendar, 61 milestones", icon: <Calendar size={16} /> },
  { key: "sales_order", title: "Track in the ERP", hint: "every record, live", icon: <Database size={16} /> },
].map((f, i) => ({ ...f, key: f.key, id: i }));

export function TodayView({ summary }: { summary?: R }) {
  const cx = useCx();
  const [d, setD] = useState<R | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => call("cx_today").then(setD), []);
  useEffect(() => { load(); }, [load, cx.tick]);
  const refresh = async () => { setBusy(true); cx.refresh(); await load(); setBusy(false); };

  const first = (cx.me.name || cx.me.email || "").split(/[ @]/)[0];
  const mail: R | undefined = d?.health?.mail;
  const rules: R | undefined = d?.health?.rules;
  const mailOk = mail?.state === "ok";
  const late: R[] = d?.overdue_milestones || [];
  const erpDown = d?.erp === "down";

  const now: R[] = d ? [
    d.approvals > 0 ? { k: "approvals", tone: "orange", title: `${d.approvals} change${d.approvals === 1 ? "" : "s"} waiting for approval`, sub: "A risky write is held until a manager decides", to: "approvals" } : null,
    d.breaches > 0 ? { k: "breaches", tone: "red", title: `${d.breaches} ERP record${d.breaches === 1 ? "" : "s"} breaking a business rule`, sub: "Found by the rules that run on every save", to: "sync" } : null,
    d.sync_failed > 0 ? { k: "sync", tone: "red", title: `${d.sync_failed} sync problem${d.sync_failed === 1 ? "" : "s"}`, sub: "An ERP change could not be processed", to: "sync" } : null,
    d.inquiries_waiting > 0 ? { k: "inq", tone: "blue", title: `${d.inquiries_waiting} new inquir${d.inquiries_waiting === 1 ? "y" : "ies"} to read`, sub: "Mail from buyers, already read and scored", to: "inquiries" } : null,
    d.health?.mail && d.health.mail.state !== "ok" ? { k: "mail", tone: "red", title: d.health.mail.state === "password_unreadable" ? "Mail has stopped — re-enter the Gmail app password" : "No mailbox is connected", sub: "Outbound mail → Settings", to: "mail" } : null,
    late.length > 0 ? { k: "late", tone: "red", title: `${late.length} milestone${late.length === 1 ? "" : "s"} past their planned date`, sub: late.slice(0, 2).map((m: R) => m.label || m.code).filter(Boolean).join(" · "), to: "tna" } : null,
  ].filter(Boolean) as R[] : [];

  return (
    <>
      <PageHead
        eyebrow="Command centre"
        title={first ? `${greet()}, ${first}` : greet()}
        sub="One place to see what the ERP holds, what needs a decision, and what the Tower is doing about it."
        acts={<>
          <Btn kind="gray" busy={busy} onClick={refresh}><RefreshCw size={14} /> Refresh</Btn>
          <Btn kind="tint" onClick={() => cx.go("ask")}><Sparkles size={14} /> Ask Cortex</Btn>
        </>}
      />

      {erpDown && <Note tone="bad">The ERP isn’t answering{d?.erp_error ? ` (${d.erp_error})` : ""}. Numbers below are from the last successful read.</Note>}

      {/* the whole job in four steps — each one opens the screen that does it */}
      <div className="cx-flow" role="list" aria-label="How an order moves through the Tower">
        {FLOW.map((f, i) => (
          <button key={f.id} role="listitem" className="cx-flow__step" onClick={() => cx.go(f.key)}>
            <span className="cx-flow__n">{i + 1}</span>
            <span className="cx-flow__ico">{f.icon}</span>
            <span className="cx-flow__txt"><b>{f.title}</b><small>{f.hint}</small></span>
            {i < FLOW.length - 1 && <ArrowRight size={14} className="cx-flow__arrow" aria-hidden="true" />}
          </button>
        ))}
      </div>

      <div className="cx-tiles">
        <Stat label="Orders in the ERP" value={summary?.orders ?? "—"} icon={<FileText size={13} />} tone="accent" onClick={() => cx.go("orders")} hint="live" />
        <Stat label="Milestones late" value={d ? late.length : "—"} icon={<Timer size={13} />} tone="red" alert={!!late.length} onClick={() => cx.go("tna")} />
        <Stat label="Waiting for approval" value={d ? d.approvals : "—"} icon={<CheckCircle2 size={13} />} tone="orange" onClick={() => cx.go("approvals")} />
        <Stat label="Open risks" value={summary?.risks ?? "—"} icon={<AlertTriangle size={13} />} tone="violet" onClick={() => cx.go("risks")} />
        <Stat label="Rule breaches" value={d ? d.breaches : "—"} icon={<Shield size={13} />} tone="red" alert={!!d?.breaches} onClick={() => cx.go("sync")} />
        <Stat label="New inquiries" value={d ? d.inquiries_waiting : "—"} icon={<Inbox size={13} />} tone="cyan" onClick={() => cx.go("inquiries")} />
      </div>

      <div className="cx-grid cx-grid--2" style={{ marginTop: 12 }}>
        <Panel title="Needs you now" sub="Most serious first" right={<Pill tone={now.length ? "orange" : "green"}>{now.length ? `${now.length} open` : "clear"}</Pill>} flush
          foot={now.length ? undefined : "Nothing is waiting. The Tower keeps checking the ERP every minute."}>
          {now.length === 0
            ? <Empty icon={<CheckCircle2 size={26} color="var(--cx-green)" />} title="Nothing needs you" text="Approvals, rule breaches and late milestones are all clear." />
            : <List>{now.map((x) => (
                <Cell key={x.k} icon={<AlertTriangle size={14} />}
                  color={x.tone === "red" ? "var(--cx-red)" : x.tone === "orange" ? "var(--cx-orange)" : "var(--cx-accent)"}
                  title={x.title} sub={x.sub} onClick={() => cx.go(x.to)} />
              ))}</List>}
        </Panel>

        <div className="cx-stack">
          <Panel title="Act now" sub="The jobs this console exists for">
            <div className="cx-acts">
              <Act icon={<Sparkles size={15} />} hint="plain words" onClick={() => cx.go("ask")}>Ask Cortex</Act>
              <Act icon={<Inbox size={15} />} hint="read and approve" onClick={() => cx.go("inquiries")}>Inquiries</Act>
              <Act icon={<FileText size={15} />} hint="live from ERP" onClick={() => cx.go("sales_order")}>Sales orders</Act>
              <Act icon={<Calendar size={15} />} hint="time and action" onClick={() => cx.go("tna")}>TnA plan</Act>
              <Act icon={<Workflow size={15} />} hint="ERP changes" onClick={() => cx.go("sync")}>Sync</Act>
              <Act icon={<BarChart3 size={15} />} hint="run a report" onClick={() => cx.go("reports")}>Reports</Act>
            </div>
          </Panel>

          <Panel title="System health" sub="Is everything the demo needs working?">
            <List>
              <Cell title="ERP" sub="Read live, never from a sample file" right={<Pill tone={erpDown ? "red" : "green"}>{erpDown ? "Not reachable" : "Live"}</Pill>} />
              <Cell title="Mailbox" sub={mail?.text || "checking…"} onClick={mailOk ? undefined : () => cx.go("mail")}
                right={<Pill tone={mailOk ? "green" : mail ? "red" : "blue"}>{mailOk ? "Reading" : mail?.state === "password_unreadable" ? "Re-enter password" : mail ? "Set up" : "…"}</Pill>} />
              <Cell title="Business rules" sub={rules?.text || "checking…"}
                right={<Pill tone={rules?.rules_off ? "orange" : rules?.scripts ? "green" : "blue"}>{rules?.scripts ? `${rules.scripts} rules` : "…"}</Pill>} />
              <Cell title="Changes to the ERP" sub="You see every value first, then confirm" right={<Pill tone={summary?.write_mode === "off" ? "red" : "blue"}>{summary?.write_mode === "all" ? "On" : summary?.write_mode === "off" ? "Off" : "Drafts only"}</Pill>} />
            </List>
            {mail && !mailOk && <Note tone="warn">{mail.state === "password_unreadable"
              ? "Mail stopped because the saved Gmail password can't be unlocked after the project moved. Open Outbound mail → Settings and type the app password again."
              : "No mail is being read yet. Open Outbound mail → Settings and add the mailbox."}</Note>}
          </Panel>
        </div>
      </div>

      <Panel title="Late on the calendar" sub={late.length ? `${late.length} milestone${late.length === 1 ? "" : "s"}` : undefined} flush className="cx-mt">
        {late.length === 0
          ? <Empty icon={<CheckCircle2 size={24} color="var(--cx-green)" />} title="Every milestone is on time" text="Nothing has passed its planned date." />
          : <div className="cx-table-wrap" style={{ border: 0, borderRadius: 0, boxShadow: "none" }}>
              <table className="cx-table"><thead><tr><th>Milestone</th><th>Order</th><th>Department</th><th>Planned</th><th className="is-num">Days late</th></tr></thead>
                <tbody>{late.slice(0, 15).map((m: R) => {
                  const days = Math.max(1, Math.round((Date.now() - new Date(m.planned_date).getTime()) / 864e5));
                  return <tr key={m.name} style={{ cursor: "pointer" }} onClick={() => cx.openDoc("TNA Milestone", m.name)}>
                    <td style={{ fontWeight: 550 }}>{m.label || m.code || m.name}</td>
                    <td>{m.sales_order || "—"}</td>
                    <td style={{ color: "var(--cx-ink-2)" }}>{m.department || "—"}</td>
                    <td style={{ color: "var(--cx-ink-2)", fontFamily: "var(--cx-mono)", fontSize: 11.5 }}>{m.planned_date || "—"}</td>
                    <td className="is-num" style={{ color: "var(--cx-red)", fontWeight: 600 }}>{days}</td>
                  </tr>;
                })}</tbody></table>
            </div>}
      </Panel>
    </>
  );
}

/* ── Inquiries ──────────────────────────────────────────────────────────── */
function Ring({ n }: { n: number }) {
  const c = n >= 80 ? "var(--cx-green)" : n >= 50 ? "var(--cx-orange)" : "var(--cx-red)";
  return <span style={{ width: 38, height: 38, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700, color: c, background: `conic-gradient(${c} ${n * 3.6}deg, var(--cx-fill) 0)`, position: "relative" }}>
    <span style={{ position: "absolute", inset: 4, borderRadius: "50%", background: "var(--cx-card)", display: "grid", placeItems: "center" }}>{n}</span></span>;
}

function InquirySheet({ id, onClose }: { id: number; onClose: () => void }) {
  const cx = useCx();
  const [a, setA] = useState<R | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (refresh = false) => { setBusy(true); setA(await call("cx_inquiry_analyse", { mail_id: id, refresh })); setBusy(false); }, [id]);
  useEffect(() => { void load(); }, [load]);
  const step = (s: R) => cx.review({
    title: s.label, sub: a?.mail?.subject, confirmLabel: "Do it",
    run: (preview, extra) => call("cx_inquiry_step", { mail_id: id, step_id: s.id, preview, ...extra }),
    done: () => void load(),
  });
  const done = a?.steps_done || {};
  const f: R = a?.fields || {};
  const keys = Object.keys(f).filter((k) => !["bom", "measurements"].includes(k) && f[k] && f[k].value !== "" && f[k].value !== false && !(Array.isArray(f[k].value) && !f[k].value.length));
  return (
    <Sheet title={a?.mail?.subject || "Inquiry"} sub={a?.mail ? `${a.mail.from || ""}` : ""} onClose={onClose} wide
      right={<button className="cx-icon-btn" aria-label="Read again" onClick={() => load(true)}><RefreshCw size={17} /></button>}>
      {!a && <ListSkel n={5} />}
      {a && !a.ok && <Note tone="bad">{a.error}</Note>}
      {a?.ok && <>
        <div className="cx-row"><Pill tone="blue">{(a.classification?.type || "").replace(/_/g, " ")}</Pill>
          {a.revision && <Pill tone="purple">revises an earlier inquiry</Pill>}{busy && <span className="cx-spin" />}</div>
        {a.needs_reading?.length > 0 && <Note tone="warn">A person needs to read: {a.needs_reading.join(", ")} (scan, image or an old file type). Nothing was guessed from it.</Note>}
        <Section>How complete is it</Section>
        <div className="cx-card"><div className="cx-row" style={{ justifyContent: "space-between" }}><b style={{ fontSize: 22 }}>{a.completeness.score}%</b><span className="cx-cell__sub">{a.completeness.have.length} of {a.completeness.have.length + a.completeness.missing.length} items</span></div>
          <div className="cx-meter" style={{ marginTop: 8 }}><i style={{ width: `${a.completeness.score}%`, background: a.completeness.score >= 70 ? "var(--cx-green)" : "var(--cx-orange)" }} /></div>
          {a.completeness.missing.length > 0 && <div className="cx-chips" style={{ marginTop: 12 }}>{a.completeness.missing.map((m: string) => <Pill key={m} tone="orange">{m}</Pill>)}</div>}
          {a.completeness.note && <Foot>{a.completeness.note}</Foot>}</div>
        <Section>What we read</Section>
        <List>{keys.length === 0 ? <Cell title="Nothing could be read with confidence" /> : keys.map((k) => (
          <Cell key={k} label title={slugTitle(k)} value={<><span className={`cx-dot cx-dot--${f[k].confidence}`} />{Array.isArray(f[k].value) ? f[k].value.join(", ") : fmtVal(f[k].value)}{f[k].ambiguous ? " (day/month unclear)" : ""}</>} />))}</List>
        {(f.bom || f.measurements) && <Foot>{f.bom ? `BOM: ${f.bom.rows} lines. ` : ""}{f.measurements ? `Measurements: ${f.measurements.rows} points.` : ""}</Foot>}
        {a.parts?.length > 0 && <><Section>Attachments</Section><List>{a.parts.map((p: R, i: number) => <Cell key={i} icon={<FileText size={16} />} color={p.ok ? "#34c759" : p.needs_reading ? "#ff9500" : "#8e8e93"} title={p.filename} sub={p.ok ? `${p.chars.toLocaleString()} characters read` : p.error} />)}</List></>}
        {a.links?.length > 0 && <Note tone="warn">The mail links to {a.links.filter((l: R) => l.file_share).length || a.links.length} file(s) online. Links are never opened automatically — ask the buyer to attach them.</Note>}
        <Section>Next steps</Section>
        <List>{(a.proposals || []).map((s: R) => (
          <Cell key={s.id} title={s.label} sub={s.blocked || s.risk || (s.needs && !done[s.needs] ? `After “${s.needs}”` : s.diff ? Object.keys(s.diff).length + " field(s) differ" : undefined)}
            right={done[s.id] ? <Pill tone="green">{done[s.id].name || "done"}</Pill> : s.request ? <Btn sm kind="tint" disabled={!!s.needs && !done[s.needs]} onClick={() => step(s)}>Review</Btn> : s.reply_draft ? <Btn sm kind="tint" onClick={async () => { const r = await call("cx_inquiry_draft_reply", { mail_id: id }); cx.toast(r.ok ? "Reply saved to Outbound Mail" : r.error); }}>Draft reply</Btn> : undefined} />
        ))}</List>
        <Foot>Nothing is created until you review it and confirm. Replies are only drafts — you send them from Outbound Mail.</Foot>
      </>}
    </Sheet>
  );
}

export function InquiriesView() {
  const cx = useCx();
  const [m, setM] = useState<R | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { call("cx_inquiry_queue").then(setM); }, [cx.tick, open]);
  return (
    <>
      <Title title="Inquiries" sub="Mail from buyers, read in any format — PDF, Excel, Word, zip, forwarded mail." />
      {!m && <ListSkel />}
      {m && !m.ok && <Note tone="bad">{m.error}</Note>}
      {m?.ok && m.mails.length === 0 && <Empty title="No inquiries yet" text="When a buyer’s mail arrives in the Inbox it appears here, already read." />}
      {m?.ok && m.mails.length > 0 && <List>{m.mails.map((x: R) => (
        <Cell key={x.id} title={x.subject || "(no subject)"} sub={`${x.from || ""} · ${ago(x.received_at)}${x.attachments ? " · 📎" : ""}`} onClick={() => setOpen(x.id)}
          right={x.analysed ? <Ring n={x.score ?? 0} /> : <Pill>Not read yet</Pill>} />))}</List>}
      {open !== null && <InquirySheet id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

/* ── Reports ────────────────────────────────────────────────────────────── */
export function ReportRunner({ name }: { name: string }) {
  const [filters, setFilters] = useState<R>({});
  const [def, setDef] = useState<R[]>([]);
  const [res, setRes] = useState<R | null>(null);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (f: R) => { setBusy(true); setRes(await call("cx_report_run", { name, filters: f })); setBusy(false); }, [name]);
  useEffect(() => {
    setRes(null); setFilters({});
    call("cx_reports").then((r) => { const rep = (r.reports || []).find((x: R) => x.name === name); setDef(rep?.filters || []); });
    void run({});
  }, [name, run]);
  const csv = () => {
    if (!res?.rows) return;
    const cols = res.columns.map((c: R) => c.fieldname);
    const esc = (v: any) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const text = [res.columns.map((c: R) => esc(c.label)).join(","), ...res.rows.map((r: R) => cols.map((c: string) => esc(r[c])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    a.download = `${name}.csv`; a.click(); URL.revokeObjectURL(a.href);
  };
  return (
    <>
      <Title title={name} sub={res?.ok ? `${res.rows.length.toLocaleString()} rows${res.truncated ? " (first 2,000)" : ""} · ${res.ms} ms` : undefined}
        right={<div className="cx-row"><button className="cx-icon-btn" aria-label="Refresh" onClick={() => run(filters)}><RefreshCw size={17} /></button>{res?.ok && <Btn kind="gray" onClick={csv}><Download size={16} /> CSV</Btn>}</div>} />
      {def.length > 0 && <div className="cx-card" style={{ marginBottom: 14 }}><div className="cx-tiles" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        {def.map((f) => <div key={f.fieldname}><label className="cx-cell__sub">{f.label}</label>
          <input className="cx-input" type={f.fieldtype === "Date" ? "date" : "text"} value={filters[f.fieldname] ?? ""} onChange={(e) => setFilters({ ...filters, [f.fieldname]: e.target.value })} onKeyDown={(e) => e.key === "Enter" && run(filters)} /></div>)}
        <div style={{ alignSelf: "end" }}><Btn kind="tint" busy={busy} onClick={() => run(filters)}>Apply</Btn></div></div></div>}
      {!res && <ListSkel n={6} />}
      {res && !res.ok && <Note tone="bad">{res.error}</Note>}
      {res?.ok && res.rows.length === 0 && <Empty title="No rows" text="Nothing matches these filters." />}
      {res?.ok && res.rows.length > 0 && (
        <div className="cx-table-wrap"><table className="cx-table"><thead><tr>{res.columns.map((c: R) => <th key={c.fieldname}>{c.label}</th>)}</tr></thead>
          <tbody>{res.rows.map((r: R, i: number) => <tr key={i}>{res.columns.map((c: R) => {
            const v = r[c.fieldname]; const num = typeof v === "number";
            return <td key={c.fieldname} className={num ? "is-num" : ""}>{v === null || v === undefined || v === "" ? "—" : num ? fmtVal(v) : String(v)}</td>;
          })}</tr>)}</tbody></table></div>)}
    </>
  );
}

export function ReportsView() {
  const cx = useCx();
  const [r, setR] = useState<R | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { call("cx_reports").then(setR); }, []);
  if (open) return <><Btn kind="plain" onClick={() => setOpen(null)}>‹ All reports</Btn><ReportRunner name={open} /></>;
  return <>
    <Title title="Reports" sub="Live from the ERP, run here." />
    {!r && <ListSkel />}{r?.ok && <List>{r.reports.map((x: R) => <Cell key={x.name} icon={<FileText size={16} />} color="#007aff" title={x.name} sub={x.ref_doctype} onClick={() => setOpen(x.name)} />)}</List>}
    {r && !r.ok && <Note tone="bad">{r.error}</Note>}
    <span style={{ display: "none" }}>{cx.tick}</span>
  </>;
}

/* ── Approvals ──────────────────────────────────────────────────────────── */
export function ApprovalsView() {
  const cx = useCx();
  const [tab, setTab] = useState<"pending" | "runs">("pending");
  const [a, setA] = useState<R | null>(null);
  const [runs, setRuns] = useState<R | null>(null);
  const [open, setOpen] = useState<R | null>(null);
  const load = useCallback(() => { call("cx_approvals", { status: "pending" }).then(setA); call("cx_runs", { limit: 40 }).then(setRuns); }, []);
  useEffect(load, [load, cx.tick]);
  /* A held write is a decision about an ERP document, and that decision belongs to whoever owns the document in the
     ERP — so "Approve" opens the ERP page instead of writing anything here. "Decided there" records what was done,
     which is what a single-person workspace needs: the tower cannot be the second pair of eyes for its only user. */
  const decide = async (id: number, decision: string, inErp = false) => {
    const r = await call("cx_decide", { approval_id: id, decision, in_erp: inErp ? 1 : 0 });
    cx.toast(r.ok ? (inErp ? `Recorded: ${decision === "approve" ? "approved" : "rejected"} in the ERP` : (decision === "approve" ? "Approved" : "Rejected")) : r.error);
    setOpen(null); load();
  };
  const openInErp = (x: R) => { if (!x?.url) { cx.toast("The ERP page for this document was not resolved."); return; } window.open(x.url, "_blank", "noopener"); };
  const undo = (id: number) => cx.review({ title: "Undo this change", sub: `Run #${id}`, confirmLabel: "Undo",
    run: async (preview) => preview ? { ok: true, preview: { operations: [], warnings: ["Everything this run wrote will be reversed where the ERP allows it. What cannot be reversed is listed afterwards."] } } : call("cx_rollback_run", { run_id: id }), done: load });
  return (
    <>
      <Title title="Approvals" sub="Risky changes wait here for a second pair of eyes." />
      <Seg value={tab} onChange={setTab} options={[{ v: "pending", l: `Waiting${a?.approvals ? ` · ${a.approvals.length}` : ""}` }, { v: "runs", l: "Recent changes" }]} />
      <div className="cx-mt">
        {tab === "pending" && (!a ? <ListSkel /> : !a.ok ? <Note tone="bad">{a.error}</Note> : a.approvals.length === 0 ? <Empty icon={<CheckCircle2 size={36} color="var(--cx-green)" />} title="All clear" text="Nothing is waiting for approval." /> :
          <List>{a.approvals.map((x: R) => <Cell key={x.id} title={x.reason} sub={`${x.requester} · ${ago(x.created_at)}`} right={<Pill tone="orange">{x.class}</Pill>} onClick={() => setOpen(x)} />)}</List>)}
        {tab === "runs" && (!runs ? <ListSkel /> : !runs.ok ? <Note tone="bad">{runs.error}</Note> : runs.runs.length === 0 ? <Empty title="No changes yet" /> :
          <List>{runs.runs.map((r: R) => <Cell key={r.id} title={`${slugTitle(r.op)} ${r.doctype} ${r.name}`.trim()} sub={`${r.actor} · ${ago(r.started_at)}`}
            right={<><Pill tone={r.status === "done" ? "green" : r.status === "compensated" ? "orange" : "red"}>{r.status}</Pill>{r.status === "done" && ["Management", "Admin"].some((x) => cx.me.roles?.includes(x)) && <Btn sm kind="gray" onClick={() => undo(r.id)}>Undo</Btn>}</>} />)}</List>)}
      </div>
      {open && <Sheet title={open.reason} sub={`Asked by ${open.requester}`} onClose={() => setOpen(null)} short
        foot={a?.can_decide ? <>
          <Btn kind="danger" onClick={() => decide(open.id, "reject")}>Reject</Btn>
          {open.url && <Btn kind="tint" onClick={() => openInErp(open)}>Decide in the ERP <ExternalLink size={13} /></Btn>}
          <Btn kind="gray" onClick={() => decide(open.id, "approve", true)}>Decided there</Btn>
        </> : undefined}>
        {open.url ? <Note tone="warn"><b>This decision is made in the ERP.</b> {open.op === "delete" ? "Deleting" : slugTitle(open.op)} <b>{open.doctype} {open.name}</b> is held, and the ERP is where it is approved, refused or done. Open it there, then record the answer here.</Note>
          : <Note tone="warn">This write is held. Decide it in the ERP, then record the answer here.</Note>}
        {open.preview?.note && <Note tone="warn">{open.preview.note}</Note>}
        <List>{(open.preview?.operations || []).filter((o: R) => o.op !== "comment").slice(0, 20).map((o: R, i: number) => <Cell key={i} title={`${slugTitle(o.op)} ${o.doctype}`} sub={o.name} />)}</List>
        {!a?.can_decide && <Foot>Only a manager can decide this.</Foot>}
        {open.mine && <Foot>You asked for this. Nobody else can approve it in a one-person workspace, so it is decided in the ERP and recorded here.</Foot>}
      </Sheet>}
    </>
  );
}

/* ── Sync & guardrails ──────────────────────────────────────────────────── */
export function SyncView() {
  const cx = useCx();
  const [s, setS] = useState<R | null>(null);
  const [b, setB] = useState<R | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => { call("cx_sync_status").then(setS); call("cx_breaches", { state: "open" }).then(setB); }, []);
  useEffect(load, [load, cx.tick]);
  const sync = async () => { setBusy(true); const r = await call("sync_changes"); setBusy(false); cx.toast(r.ok ? (r.skipped ? "Already syncing" : `Checked ${r.poll?.polled ?? 0} kinds of record`) : r.error); load(); };
  const dismiss = async (id: number) => { const r = await call("cx_breach_decide", { breach_id: id, decision: "dismiss" }); cx.toast(r.ok ? "Dismissed" : r.error); load(); };
  return (
    <>
      <Title title="Sync & guardrails" sub="Changes made directly in the ERP are picked up here, and checked against the same rules."
        right={<Btn busy={busy} onClick={sync}><RefreshCw size={16} /> Sync now</Btn>} />
      {s && !s.ok && <Note tone="bad">{s.error}</Note>}
      {s?.ok && <div className="cx-tiles">
        <div className="cx-tile"><span className="cx-tile__n">{s.queue.new}</span><span className="cx-tile__l">Waiting to check</span></div>
        <div className="cx-tile"><span className="cx-tile__n" style={{ color: s.queue.failed ? "var(--cx-red)" : undefined }}>{s.queue.failed}</span><span className="cx-tile__l">Failed</span></div>
        <div className="cx-tile"><span className="cx-tile__n" style={{ color: s.breaches_open ? "var(--cx-orange)" : undefined }}>{s.breaches_open}</span><span className="cx-tile__l">Open breaches</span></div>
        <div className="cx-tile"><span className="cx-tile__n">{s.webhook_configured ? "On" : "Off"}</span><span className="cx-tile__l">Instant updates (webhook)</span></div></div>}
      {s?.ok && !s.webhook_configured && <Note>Instant updates from the ERP aren’t set up, so changes are found when this page or the dashboard syncs. Ask your administrator to switch on the webhook.</Note>}
      <Section>Rule breaches</Section>
      {!b ? <ListSkel n={2} /> : !b.ok ? <Note tone="bad">{b.error}</Note> : b.breaches.length === 0 ? <List><Cell icon={<Shield size={17} />} color="#34c759" title="No breaches" sub="Everything in the ERP follows the rules." /></List> :
        <List>{b.breaches.map((x: R) => <Cell key={x.id} icon={<AlertTriangle size={16} />} color="#ff9500" title={`${x.doctype} ${x.name}`} sub={x.message}
          onClick={() => cx.openDoc(x.doctype, x.name)} right={<Btn sm kind="gray" onClick={() => dismiss(x.id)}>Dismiss</Btn>} />)}</List>}
      <Foot>The tower never reverts the ERP by itself. A breach is for a person to look at.</Foot>
    </>
  );
}

/* ── Script runtime (admin) ─────────────────────────────────────────────── */
export function TsrView() {
  const cx = useCx();
  const [t, setT] = useState<R | null>(null);
  const [c, setC] = useState<R | null>(null);
  const [q, setQ] = useState("");
  const load = useCallback(() => { call("tsr_status").then(setT); }, []);
  useEffect(load, [load]);
  const kill = (off: boolean) => cx.review({ title: off ? "Switch all rules off?" : "Switch rules back on", confirmLabel: off ? "Switch off" : "Switch on",
    run: async (preview, extra) => preview ? { ok: true, preview: { warnings: [off ? "Business rules stop being checked. Numbering and the production ledger keep working. Use this only to stop a faulty rule." : "Rules are checked again."] } } : call("tsr_kill_switch", { state: off ? "off" : "on", ...extra }),
    done: load });
  const toggle = async (n: string, on: boolean) => { const r = await call("tsr_set_script", { name: n, enabled: on }); cx.toast(r.ok ? (on ? "On" : "Off") : r.error); load(); };
  const shown = (t?.scripts || []).filter((s: R) => !q || (s.name + s.doctype + s.event).toLowerCase().includes(q.toLowerCase())).slice(0, 80);
  return (
    <>
      <Title title="Script runtime" sub="The business rules that run when something is saved." />
      {t && !t.ok && <Note tone="bad">{t.error}</Note>}
      {t?.ok && <>
        <List>
          <Cell title="Business rules" sub={t.rules_off ? "Off — nothing is being checked" : `${t.count} scripts active`} right={<Switch on={!t.rules_off} onChange={(on) => kill(!on)} label="Rules" />} />
          <Cell title="Rules match the repository" sub={t.vendor.ok ? `${t.vendor.scripts} scripts verified` : `Differs: ${(t.vendor.drift || []).join(", ") || t.vendor.error}`} right={<Pill tone={t.vendor.ok ? "green" : "red"}>{t.vendor.ok ? "OK" : "Check"}</Pill>} />
          <Cell title="ERP connection" sub={c ? (c.ok ? `${c.arinox_doctypes} Arinox record types · signed in as ${c.api_user}` : c.error) : "Not checked"} right={<Btn sm kind="tint" onClick={async () => setC(await call("cx_connection"))}>Check</Btn>} />
        </List>
        {c?.ok && c.missing_core_doctypes?.length > 0 && <Note tone="bad">Missing on the ERP: {c.missing_core_doctypes.join(", ")}. The Arinox layer isn’t loaded there.</Note>}
        {c?.ok && c.server_scripts_on_erp > 0 && <Note tone="warn">The ERP also has {c.server_scripts_on_erp} server scripts. If they are switched on there, every rule would run twice.</Note>}
        <Section>Scripts</Section>
        <div className="cx-search"><Search size={17} /><input className="cx-input" type="search" placeholder="Search scripts" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="cx-mt"><List>{shown.map((s: R) => <Cell key={s.name} title={slugTitle(s.name)} sub={`${s.doctype || s.type} · ${s.event} · ${s.runs} runs${s.failures ? ` · ${s.failures} failed` : ""}${s.avg_ms ? ` · ${s.avg_ms} ms` : ""}`}
          right={<Switch on={s.enabled} onChange={(on) => toggle(s.name, on)} label={s.name} />} />)}</List></div>
      </>}
    </>
  );
}

/* ── Users (admin) ──────────────────────────────────────────────────────── */
export function AdminView() {
  const cx = useCx();
  const [u, setU] = useState<R | null>(null);
  const [open, setOpen] = useState<R | null>(null);
  const load = useCallback(() => { call("list_tower_users").then(setU); }, []);
  useEffect(load, [load]);
  const save = async (x: R, patch: R) => { const r = await call("set_tower_user", { email: x.email, ...patch }); cx.toast(r.ok ? "Saved" : r.error); load(); if (r.ok) setOpen({ ...x, ...(patch.roles ? { roles: patch.roles } : {}), ...(patch.active !== undefined ? { active: patch.active } : {}) }); };
  return (
    <>
      <Title title="Users & roles" sub="What each person can see and change." />
      {u && !u.ok && <Note tone="bad">{u.error}</Note>}
      {!u && <ListSkel />}
      {u?.users && <List>{u.users.map((x: R) => <Cell key={x.email} title={x.name || x.email} sub={`${x.email}${x.roles.length ? " · " + x.roles.join(", ") : " · no role yet"}`}
        right={!x.active ? <Pill tone="red">Off</Pill> : x.is_admin ? <Pill tone="blue">Admin</Pill> : undefined} onClick={() => setOpen(x)} />)}</List>}
      {u?.users && u.users.some((x: R) => !x.roles.length) && <Note tone="warn">People with no role can look around but can’t change anything. Tap a person to give them a role.</Note>}
      {open && u && <Sheet title={open.name || open.email} sub={open.email} onClose={() => setOpen(null)}>
        <Section>Roles</Section>
        <div className="cx-chips">{u.all_roles.map((r: string) => { const on = open.roles.includes(r);
          return <button key={r} className={`cx-chip${on ? " is-on" : ""}`} onClick={() => save(open, { roles: on ? open.roles.filter((x: string) => x !== r) : [...open.roles, r] })}>{r}</button>; })}</div>
        <Section>ERP user</Section>
        <ErpUser value={open.erp_user} onSave={(v) => save(open, { erp_user: v })} />
        <Foot>Used so rules that check “who is doing this” see the right person.</Foot>
        <Section>Account</Section>
        <List><Cell title="Active" right={<Switch on={open.active} onChange={(on) => save(open, { active: on })} label="Active" />} /></List>
      </Sheet>}
    </>
  );
}
function ErpUser({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value || "");
  const ref = useRef<HTMLInputElement>(null);
  return <div className="cx-row"><input ref={ref} className="cx-input cx-grow" placeholder="name@company.com" value={v} onChange={(e) => setV(e.target.value)} /><Btn kind="tint" onClick={() => onSave(v)}>Save</Btn></div>;
}

/* ── Search ─────────────────────────────────────────────────────────────── */
export function SearchSheet({ onClose }: { onClose: () => void }) {
  const cx = useCx();
  const [q, setQ] = useState("");
  const [r, setR] = useState<R[] | null>(null);
  const t = useRef<number | null>(null);
  const change = (v: string) => {
    setQ(v);
    if (t.current) window.clearTimeout(t.current);
    if (v.trim().length < 2) { setR(null); return; }
    t.current = window.setTimeout(async () => { const x = await call("cx_search", { q: v }); setR(x.ok ? x.results : []); }, 280);
  };
  return (
    <Sheet title="Search" onClose={onClose}>
      <div className="cx-search"><Search size={17} /><input autoFocus className="cx-input" type="search" placeholder="Order, style, customer, PO…" value={q} onChange={(e) => change(e.target.value)} /></div>
      <div className="cx-mt">
        {r === null && <Foot>Type at least two characters.</Foot>}
        {r && r.length === 0 && <Empty title="No match" text="Try a different number or name." />}
        {r && r.length > 0 && <List>{r.map((x) => <Cell key={x.doctype + x.name} title={x.name} sub={x.doctype} onClick={() => { onClose(); cx.openDoc(x.doctype, x.name); }} />)}</List>}
      </div>
    </Sheet>
  );
}
