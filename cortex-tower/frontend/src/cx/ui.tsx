import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, Info, Loader2, X } from "lucide-react";
import { fmtVal, uid } from "./api";
import type { R } from "./api";
/* shadcn/ui primitives — the controls in this file are thin wrappers over them, so every screen
   gets the same button, badge, switch and tab behaviour (focus rings, disabled states, a11y roles). */
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch as UiSwitch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/* ── shared context ─────────────────────────────────────────────────────── */
export interface Review { title: string; sub?: string; run: (preview: boolean, extra: R) => Promise<R>; done?: (r: R) => void; confirmLabel?: string; }
export interface Ctx {
  me: R;
  go: (key: string) => void;
  openDoc: (doctype: string, name: string) => void;
  newDoc: (doctype: string, initial?: R) => void;
  toast: (msg: string) => void;
  review: (r: Review) => void;
  refresh: () => void;
  tick: number;
}
export const CxCtx = createContext<Ctx>(null as unknown as Ctx);
export const useCx = () => useContext(CxCtx);

/* ── controls ───────────────────────────────────────────────────────────── */
export function Btn(p: { children: ReactNode; onClick?: () => void; kind?: "tint" | "gray" | "danger" | "plain"; sm?: boolean; block?: boolean; disabled?: boolean; busy?: boolean; type?: "button" | "submit" }) {
  const variant = p.kind === "danger" ? "destructive" : p.kind === "gray" ? "outline" : p.kind === "plain" ? "ghost" : "default";
  return (
    <Button
      type={p.type || "button"}
      variant={variant}
      size={p.sm ? "sm" : "default"}
      className={cn("gap-2", p.block && "w-full")}
      onClick={p.onClick}
      disabled={p.disabled || p.busy}
    >
      {p.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
      {p.children}
    </Button>
  );
}

export const Pill = (p: { children: ReactNode; tone?: "green" | "orange" | "red" | "blue" | "purple" }) => {
  const cls = {
    green: "border-emerald-200 bg-emerald-50 text-emerald-700",
    orange: "border-amber-200 bg-amber-50 text-amber-700",
    red: "border-red-200 bg-red-50 text-red-700",
    blue: "border-[#c9d3fd] bg-[#eef1fe] text-[#3d59e8]",
    purple: "border-violet-200 bg-violet-50 text-violet-700",
  };
  return <Badge variant="outline" className={cn("rounded-full px-2 py-0 text-[10.5px] font-medium", p.tone && cls[p.tone])}>{p.children}</Badge>;
};
export const Section = (p: { children: ReactNode; right?: ReactNode }) => <div className="cx-section"><span>{p.children}</span>{p.right}</div>;
export const List = (p: { children: ReactNode }) => <div className="cx-list">{p.children}</div>;
export const Foot = (p: { children: ReactNode }) => <div className="cx-foot">{p.children}</div>;

export function Cell(p: { title: ReactNode; sub?: ReactNode; value?: ReactNode; onClick?: () => void; chev?: boolean; icon?: ReactNode; color?: string; label?: boolean; right?: ReactNode }) {
  const inner = (
    <>
      {p.icon && <span className="cx-cell__icon" style={{ background: p.color || "var(--cx-accent)" }}>{p.icon}</span>}
      <span className="cx-cell__main"><div className="cx-cell__title">{p.title}</div>{p.sub ? <div className="cx-cell__sub">{p.sub}</div> : null}</span>
      {p.value !== undefined && <span className="cx-cell__val">{p.value}</span>}
      {p.right}
      {(p.chev ?? !!p.onClick) && <ChevronRight size={15} className="cx-cell__chev" />}
    </>
  );
  const cls = `cx-cell${p.label ? " is-label" : ""}`;
  return p.onClick ? <button type="button" className={cls} onClick={p.onClick}>{inner}</button> : <div className={cls}>{inner}</div>;
}

export function Seg<T extends string>(p: { value: T; options: { v: T; l: string }[]; onChange: (v: T) => void }) {
  return (
    <Tabs value={p.value} onValueChange={(v) => p.onChange(v as T)}>
      <TabsList className="h-8 gap-0.5 rounded-lg bg-[#f2f4f7] p-0.5">
        {p.options.map((o) => (
          <TabsTrigger
            key={o.v}
            value={o.v}
            className="h-7 rounded-md px-3 text-[12.5px] data-[state=active]:bg-white data-[state=active]:text-[#111827] data-[state=active]:shadow-sm"
          >
            {o.l}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

export const Switch = (p: { on: boolean; onChange: (b: boolean) => void; label?: string }) =>
  <UiSwitch checked={p.on} onCheckedChange={p.onChange} aria-label={p.label} className="data-[state=checked]:bg-[#4f6ef7]" />;

/* ── structure: page head, panel, stat, quick action ────────────────────── */
export function PageHead(p: { eyebrow?: string; title: ReactNode; sub?: ReactNode; acts?: ReactNode }) {
  return (
    <div className="cx-head">
      <div className="cx-head__main">
        {p.eyebrow && <div className="cx-head__eyebrow">{p.eyebrow}</div>}
        <h1 className="cx-large">{p.title}</h1>
        {p.sub && <p className="cx-lead">{p.sub}</p>}
      </div>
      {p.acts && <div className="cx-head__acts">{p.acts}</div>}
    </div>
  );
}

export function Panel(p: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; foot?: ReactNode; children: ReactNode; flush?: boolean; className?: string }) {
  return (
    <section className={`cx-panel${p.className ? " " + p.className : ""}`}>
      {(p.title || p.right) && (
        <header className="cx-panel__head">
          <div><div className="cx-panel__title">{p.title}</div>{p.sub && <div className="cx-panel__sub">{p.sub}</div>}</div>
          <span className="cx-panel__sp" />
          {p.right}
        </header>
      )}
      <div className={`cx-panel__body${p.flush ? " cx-panel__body--flush" : ""}`}>{p.children}</div>
      {p.foot && <div className="cx-panel__foot">{p.foot}</div>}
    </section>
  );
}

/** One number with its label. The unit of a command centre. */
export function Stat(p: { label: string; value: ReactNode; icon?: ReactNode; tone?: "accent" | "green" | "orange" | "red" | "violet" | "cyan"; hint?: ReactNode; onClick?: () => void; alert?: boolean }) {
  const color = p.tone === "green" ? "var(--cx-green)" : p.tone === "orange" ? "var(--cx-orange)" : p.tone === "red" ? "var(--cx-red)" : p.tone === "violet" ? "var(--cx-violet)" : p.tone === "cyan" ? "var(--cx-cyan)" : "var(--cx-accent)";
  const soft = p.tone === "green" ? "var(--cx-green-soft)" : p.tone === "orange" ? "var(--cx-orange-soft)" : p.tone === "red" ? "var(--cx-red-soft)" : "var(--cx-accent-soft)";
  return (
    <button className={`cx-tile${p.alert ? " is-alert" : ""}`} onClick={p.onClick} disabled={!p.onClick} style={{ cursor: p.onClick ? "pointer" : "default" }}>
      <span className="cx-tile__top">
        {p.icon && <span className="cx-tile__ico" style={{ background: soft, color }}>{p.icon}</span>}
        <span style={{ flex: 1 }} />
        {p.hint && <span style={{ fontSize: 11, color: "var(--cx-ink-4)" }}>{p.hint}</span>}
      </span>
      <span className="cx-tile__n" style={{ color: p.alert ? "var(--cx-red)" : undefined }}>{p.value}</span>
      <span className="cx-tile__l">{p.label}</span>
    </button>
  );
}

export function Act(p: { children: ReactNode; hint?: string; icon?: ReactNode; onClick: () => void }) {
  return (
    <button className="cx-act" onClick={p.onClick}>
      {p.icon}
      <span style={{ minWidth: 0 }}><b>{p.children}</b>{p.hint && <small>{p.hint}</small>}</span>
    </button>
  );
}

/* ── notes, empty, loading ──────────────────────────────────────────────── */
export function Note(p: { children: ReactNode; tone?: "warn" | "bad" | "ok" }) {
  const Icon = p.tone === "bad" ? AlertTriangle : p.tone === "ok" ? CheckCircle2 : p.tone === "warn" ? AlertTriangle : Info;
  const style = p.tone === "bad"
    ? "border-red-200 bg-red-50 text-red-800"
    : p.tone === "warn"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : p.tone === "ok"
        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
        : "border-[#dbe2fe] bg-[#f5f7ff] text-[#2b3a67]";
  return (
    <div className={cn("mb-3 flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-[12.5px] leading-relaxed", style)}
      role={p.tone === "bad" ? "alert" : "status"}>
      <Icon size={15} className="mt-0.5 shrink-0" />
      <div>{p.children}</div>
    </div>
  );
}
export const Empty = (p: { title: string; text?: string; action?: ReactNode; icon?: ReactNode }) =>
  <div className="cx-empty">{p.icon}<h3>{p.title}</h3>{p.text && <p>{p.text}</p>}{p.action && <div style={{ marginTop: 14 }}>{p.action}</div>}</div>;
export const Skel = (p: { h?: number; w?: number | string; mt?: number }) =>
  <Skeleton className="rounded-md bg-[#eef1f5]" style={{ height: p.h || 42, width: p.w || "100%", marginTop: p.mt || 0 }} />;
export const Spinner = () => <span className="cx-spin" aria-label="Loading" />;
export function ListSkel({ n = 5 }: { n?: number }) { return <div className="cx-list" aria-busy="true">{Array.from({ length: n }).map((_, i) => <div key={i} style={{ padding: 12 }}><Skel h={12} w="48%" /><Skel h={9} w="30%" mt={7} /></div>)}</div>; }

export function Title(p: { title: string; sub?: string; right?: ReactNode }) {
  return <PageHead title={p.title} sub={p.sub} acts={p.right} />;
}

/* ── sheet ──────────────────────────────────────────────────────────────── */
export function Sheet(p: { title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode; foot?: ReactNode; wide?: boolean; short?: boolean; right?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ y: number } | null>(null);
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") p.onClose(); };
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => { document.body.style.overflow = prev; window.removeEventListener("keydown", onKey); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const start = (e: React.TouchEvent) => { drag.current = { y: e.touches[0].clientY }; };
  const move = (e: React.TouchEvent) => {
    if (!drag.current || !ref.current) return;
    if (window.innerWidth > 700) return; /* drag-to-dismiss is a phone gesture only */
    const dy = Math.max(0, e.touches[0].clientY - drag.current.y);
    ref.current.style.transition = "none";
    ref.current.style.transform = `translateY(${dy}px)`;
  };
  const end = (e: React.TouchEvent) => {
    if (!drag.current || !ref.current) return;
    const dy = e.changedTouches[0].clientY - drag.current.y;
    drag.current = null;
    ref.current.style.transition = "transform .22s var(--cx-ease)";
    if (dy > 110) { ref.current.style.transform = "translateY(100%)"; setTimeout(p.onClose, 160); } else ref.current.style.transform = "";
  };
  return (
    <>
      <div className="cx-scrim" onClick={p.onClose} />
      <div className={`cx-sheet${p.wide ? " cx-sheet--wide" : ""}${p.short ? " is-short" : ""}`} role="dialog" aria-modal="true" ref={ref} tabIndex={-1}>
        <div onTouchStart={start} onTouchMove={move} onTouchEnd={end}>
          <div className="cx-sheet__grab" />
          <div className="cx-sheet__head">
            <div className="cx-sheet__title">{p.title}{p.sub && <div className="cx-sheet__sub">{p.sub}</div>}</div>
            {p.right}
            <button className="cx-icon-btn" onClick={p.onClose} aria-label="Close"><X size={16} /></button>
          </div>
        </div>
        <div className="cx-sheet__body">{p.children}</div>
        {p.foot && <div className="cx-sheet__foot">{p.foot}</div>}
      </div>
    </>
  );
}

/* ── review sheet: preview → confirm → result (used by every write) ───────── */
const VERB: Record<string, string> = { insert: "Create", save: "Change", submit: "Submit", cancel: "Cancel", delete: "Delete", set_value: "Update", call: "Run" };

function summarise(ops: R[]): { text: string; changes?: R }[] {
  const out: { text: string; changes?: R }[] = [];
  const counts: Record<string, number> = {};
  for (const o of ops) {
    if (o.op === "comment") continue;
    const key = `${o.op}|${o.doctype}`;
    counts[key] = (counts[key] || 0) + 1;
  }
  const shown: Record<string, boolean> = {};
  for (const o of ops) {
    if (o.op === "comment") continue;
    const key = `${o.op}|${o.doctype}`;
    if (counts[key] > 3) {
      if (!shown[key]) { shown[key] = true; out.push({ text: `${VERB[o.op] || o.op} ${o.doctype} × ${counts[key]}` }); }
    } else {
      const ch = o.changes || (o.values ? Object.fromEntries(Object.entries(o.values).map(([k, v]) => [k, { to: v }])) : undefined);
      out.push({ text: `${VERB[o.op] || o.op} ${o.doctype}${o.name && !String(o.name).startsWith("(new") ? " " + o.name : ""}`, changes: ch });
    }
  }
  return out;
}

export function ReviewSheet({ review, onClose, toast }: { review: Review; onClose: () => void; toast: (m: string) => void }) {
  const [stage, setStage] = useState<"loading" | "preview" | "running" | "done" | "error" | "approval" | "conflict">("loading");
  const [data, setData] = useState<R>({});
  const key = useRef(uid());
  const load = useCallback(async () => {
    setStage("loading");
    const r = await review.run(true, {});
    setData(r);
    setStage(r.ok ? "preview" : r.conflict ? "conflict" : "error");
  }, [review]);
  useEffect(() => { void load(); }, [load]);

  const go = async () => {
    setStage("running");
    const r = await review.run(false, { idem_key: key.current });
    setData(r);
    if (r.ok) { setStage("done"); toast(r.replayed ? "Already done" : "Done"); review.done?.(r); }
    else if (r.needs_approval) { setStage("approval"); }
    else setStage(r.conflict ? "conflict" : "error");
  };
  const pv = data.preview || {};
  const lines = summarise(pv.operations || []);
  return (
    <Sheet title={review.title} sub={review.sub} onClose={onClose} short={stage !== "preview"}
      foot={stage === "preview" ? <><Btn kind="gray" onClick={onClose}>Not now</Btn><Btn onClick={go}>{review.confirmLabel || "Confirm"}</Btn></>
        : stage === "done" || stage === "approval" ? <Btn block onClick={onClose}>Close</Btn>
        : stage === "error" || stage === "conflict" ? <><Btn kind="gray" onClick={onClose}>Close</Btn><Btn kind="tint" onClick={load}>Check again</Btn></> : undefined}>
      {stage === "loading" && <div style={{ padding: 24, textAlign: "center" }}><Spinner /><p className="cx-lead">Checking the rules…</p></div>}
      {stage === "running" && <div style={{ padding: 24, textAlign: "center" }}><Spinner /><p className="cx-lead">Saving to the ERP…</p></div>}
      {stage === "preview" && <>
        <Note>This is a preview — nothing has been saved yet.</Note>
        {pv.class === "risky" && <Note tone="warn">{pv.note || "This changes stock or ledger records and needs a manager's approval."}</Note>}
        {pv.partial && <Note tone="warn">Part of this could not be simulated. The checks will run for real when you confirm.</Note>}
        {lines.length > 0 && <><Section>What will happen</Section>
          <List>{lines.map((l, i) => <div key={i}><Cell title={l.text}
              sub={l.changes && Object.keys(l.changes).length ? Object.entries(l.changes).slice(0, 5).map(([k, v]: any) => `${k}: ${v.from !== undefined && v.from !== null ? fmtVal(v.from) + " → " : ""}${fmtVal(v.to)}`).join(" · ") : undefined} /></div>)}</List></>}
        {(pv.warnings || []).length > 0 && <><Section>Heads-up</Section><List>{pv.warnings.map((w: string, i: number) => <Cell key={i} title={w} />)}</List></>}
        {pv.scripts?.length > 0 && <Foot>Rules checked: {pv.scripts.length}</Foot>}
      </>}
      {stage === "done" && <>
        <Note tone="ok">Saved. {data.written?.length ? `${data.written.length} record${data.written.length === 1 ? "" : "s"} written.` : ""}</Note>
        {(data.messages || []).map((m: R, i: number) => <Note key={i} tone="warn">{m.message}</Note>)}
        {(data.skipped_writes || []).length > 0 && <Foot>{data.skipped_writes.length} status update(s) on cancelled records were not written (the ERP shows “Cancelled” from the record itself).</Foot>}
      </>}
      {stage === "approval" && <><Note tone="warn">Sent for approval (#{data.approval_id}). A manager will see it under Approvals. Nothing has changed yet.</Note></>}
      {stage === "conflict" && <Note tone="warn">{data.error || "Someone changed this in the ERP while you were looking at it."} Reload it and try again — nothing was overwritten.</Note>}
      {stage === "error" && <>
        <Note tone="bad">{data.error || "Something went wrong."}</Note>
        {(data.undone || []).length > 0 && <Foot>Already undone: {data.undone.join(", ")}</Foot>}
        {(data.attention || []).length > 0 && <Note tone="bad">A manager needs to look: {data.attention.join("; ")}</Note>}
      </>}
    </Sheet>
  );
}

/* ── toast hook ─────────────────────────────────────────────────────────── */
export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  const t = useRef<number | null>(null);
  const show = useCallback((m: string) => { setMsg(m); if (t.current) window.clearTimeout(t.current); t.current = window.setTimeout(() => setMsg(null), 3200); }, []);
  const node = msg ? <div className="cx-toast" role="status" aria-live="polite">{msg}</div> : null;
  return { show, node };
}
