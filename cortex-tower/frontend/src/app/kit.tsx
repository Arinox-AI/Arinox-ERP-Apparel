import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import { call } from "../cx/api";
import type { R } from "../cx/api";

export type { R };
export { call };

/* ── formatting ─────────────────────────────────────────────────────────── */
export function money(v: any, ccy = "USD", digits = 2): string {
  const n = Number(v);
  if (v === null || v === undefined || v === "" || isNaN(n)) return "—";
  return `${ccy ? ccy + " " : ""}${n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}
export function num(v: any, digits = 0): string {
  const n = Number(v);
  if (v === null || v === undefined || v === "" || isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
export function short(v: number): string {
  if (!isFinite(v)) return "—";
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (Math.abs(v) >= 1e4) return Math.round(v / 1e3) + "k";
  return Math.round(v).toLocaleString();
}
export function when(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(String(iso).replace(" ", "T"));
  if (isNaN(d.getTime())) return String(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const days = (now.getTime() - d.getTime()) / 86400000;
  if (days < 6) return d.toLocaleDateString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: now.getFullYear() === d.getFullYear() ? undefined : "numeric" });
}
export function day(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
  return isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/* ── data hook ──────────────────────────────────────────────────────────── */
export function useCall(name: string, params: R = {}, deps: any[] = []) {
  const [data, setData] = useState<R | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const load = useCallback(async (silent = false) => {
    const my = ++seq.current;
    if (!silent) setLoading(true);
    const r = await call(name, params);
    if (my !== seq.current) return r;
    if (r.ok === false) { setError(r.error || "Something went wrong."); } else { setError(""); setData(r); }
    setLoading(false);
    return r;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, JSON.stringify(params)]);
  useEffect(() => { void load(); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, ...deps]);
  return { data, error, loading, reload: load, setData };
}

/* ── toasts (one per workspace) ─────────────────────────────────────────── */
type Toaster = (msg: string, tone?: "ok" | "bad") => void;
export const ToastCtx = createContext<Toaster>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastHost({ children }: { children: ReactNode }) {
  const [t, setT] = useState<{ msg: string; tone?: string } | null>(null);
  const timer = useRef<number | null>(null);
  const show: Toaster = useCallback((msg, tone) => {
    if (timer.current) window.clearTimeout(timer.current);
    setT({ msg, tone });
    timer.current = window.setTimeout(() => setT(null), msg.length > 120 || tone === "bad" ? 12000 : 5000);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {t && <div className="ws-toast" role="status" aria-live="polite">
        {t.tone === "bad" ? <AlertTriangle size={16} color="#fca5a5" /> : <CheckCircle2 size={16} color="#86efac" />}
        <span>{t.msg}</span><button onClick={() => setT(null)} aria-label="Dismiss">×</button>
      </div>}
    </ToastCtx.Provider>
  );
}

/* ── controls ───────────────────────────────────────────────────────────── */
type BtnKind = "primary" | "dark" | "ghost" | "plain" | "danger";
export function Btn(p: { children?: ReactNode; onClick?: () => void; kind?: BtnKind; sm?: boolean; icon?: boolean; disabled?: boolean; busy?: boolean; title?: string; type?: "button" | "submit" }) {
  return (
    <button type={p.type || "button"} title={p.title} className={`ws-btn ws-btn--${p.kind || "ghost"}${p.sm ? " ws-btn--sm" : ""}${p.icon ? " ws-btn--icon" : ""}`}
      onClick={p.onClick} disabled={p.disabled || p.busy} aria-busy={p.busy || undefined}>
      {p.busy && <Loader2 size={14} className="ws-spin" />}{p.children}
    </button>
  );
}
export type Tone = "ok" | "bad" | "warn" | "info" | "violet" | "teal" | "dark" | undefined;
export const Badge = (p: { children: ReactNode; tone?: Tone; title?: string }) => <span title={p.title} className={`ws-badge${p.tone ? " ws-badge--" + p.tone : ""}`}>{p.children}</span>;

export const STAGE_TONE: Record<string, Tone> = { inquiry: undefined, costing: "warn", quoted: "info", negotiating: "violet", accepted: "teal", contract: "dark", order: "ok", lost: "bad" };
export const StageBadge = ({ stage, label }: { stage: string; label?: string }) => <Badge tone={STAGE_TONE[stage]}>{label || stage}</Badge>;
export const LABEL_TONE: Record<string, Tone> = { inquiry: "info", new_order: "ok", order_amendment: "warn", invoice: "violet", remittance: "teal", query: undefined, other: undefined, noise: undefined };

export function Field(p: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return <label className="ws-field" style={p.wide ? { gridColumn: "1 / -1" } : undefined}><span>{p.label}</span>{p.children}{p.hint && <small>{p.hint}</small>}</label>;
}
export function Input(p: { value: any; onChange: (v: string) => void; placeholder?: string; type?: string; sm?: boolean; num?: boolean; disabled?: boolean; list?: string; onEnter?: () => void; autoFocus?: boolean; "aria-label"?: string }) {
  return <input className={`ws-input${p.sm ? " ws-input--sm" : ""}${p.num ? " is-num" : ""}`} value={p.value ?? ""} placeholder={p.placeholder} type={p.type || "text"}
    disabled={p.disabled} list={p.list} autoFocus={p.autoFocus} aria-label={p["aria-label"]} step={p.type === "number" ? "any" : undefined}
    onChange={(e) => p.onChange(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && p.onEnter) p.onEnter(); }} />;
}
export function Select(p: { value: any; onChange: (v: string) => void; options: (string | { v: string; l: string })[]; placeholder?: string; disabled?: boolean; sm?: boolean }) {
  return (
    <select className={`ws-select${p.sm ? " ws-input--sm" : ""}`} value={p.value ?? ""} disabled={p.disabled} onChange={(e) => p.onChange(e.target.value)}>
      {p.placeholder !== undefined && <option value="">{p.placeholder}</option>}
      {p.options.map((o) => typeof o === "string" ? <option key={o} value={o}>{o}</option> : <option key={o.v} value={o.v}>{o.l}</option>)}
    </select>
  );
}
export function Textarea(p: { value: string; onChange: (v: string) => void; rows?: number; placeholder?: string }) {
  return <textarea className="ws-textarea" rows={p.rows || 6} value={p.value} placeholder={p.placeholder} onChange={(e) => p.onChange(e.target.value)} />;
}

export function Card(p: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; flush?: boolean; className?: string }) {
  return (
    <section className={`ws-card${p.className ? " " + p.className : ""}`}>
      {(p.title || p.right) && <div className="ws-card__head">{p.title && <h3>{p.title}</h3>}{p.sub && <span className="ws-sub">{p.sub}</span>}{p.right && <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>{p.right}</div>}</div>}
      <div className={`ws-card__body${p.flush ? " ws-card__body--flush" : ""}`}>{p.children}</div>
    </section>
  );
}
export function Head(p: { title: ReactNode; sub?: ReactNode; acts?: ReactNode }) {
  return <div className="ws-head"><div><h2>{p.title}</h2>{p.sub && <p>{p.sub}</p>}</div>{p.acts && <div className="ws-head__acts">{p.acts}</div>}</div>;
}
export function Note(p: { children: ReactNode; tone?: "warn" | "bad" | "ok" }) {
  const Icon = p.tone === "ok" ? CheckCircle2 : p.tone ? AlertTriangle : Info;
  return <div className={`ws-note${p.tone ? " ws-note--" + p.tone : ""}`} role={p.tone === "bad" ? "alert" : undefined}><Icon size={16} /><div>{p.children}</div></div>;
}
export const Empty = (p: { title: string; text?: ReactNode; action?: ReactNode }) => <div className="ws-empty"><b>{p.title}</b>{p.text && <div>{p.text}</div>}{p.action && <div className="ws-mt">{p.action}</div>}</div>;
export const Skel = (p: { h?: number; w?: number | string; mt?: number }) => <div className="ws-skel" style={{ height: p.h || 14, width: p.w || "100%", marginTop: p.mt || 0 }} />;
export function Loading({ rows = 4 }: { rows?: number }) {
  return <div aria-busy="true">{Array.from({ length: rows }).map((_, i) => <Skel key={i} h={i === 0 ? 22 : 54} w={i === 0 ? "30%" : "100%"} mt={i ? 10 : 0} />)}</div>;
}

export function Modal(p: { title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode; foot?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") p.onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [p]);
  return (
    <div className="ws-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) p.onClose(); }}>
      <div className={`ws-modal${p.wide ? " ws-modal--wide" : ""}`} role="dialog" aria-modal="true">
        <div className="ws-modal__head"><div><h3>{p.title}</h3>{p.sub && <p>{p.sub}</p>}</div><button className="ws-x" onClick={p.onClose} aria-label="Close"><X size={18} /></button></div>
        <div className="ws-modal__body">{p.children}</div>
        {p.foot && <div className="ws-modal__foot">{p.foot}</div>}
      </div>
    </div>
  );
}

export function Kpi(p: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; onClick?: () => void; tone?: "bad" | "warn" | "ok" }) {
  const color = p.tone === "bad" ? "var(--ws-bad)" : p.tone === "warn" ? "var(--ws-warn)" : p.tone === "ok" ? "var(--ws-ok)" : undefined;
  return (
    <div className={`ws-card ws-kpi${p.onClick ? " is-click" : ""}`} onClick={p.onClick} role={p.onClick ? "button" : undefined} tabIndex={p.onClick ? 0 : undefined}
      onKeyDown={(e) => { if (p.onClick && (e.key === "Enter" || e.key === " ")) p.onClick(); }}>
      <div className="ws-kpi__label">{p.icon}{p.label}</div>
      <div className="ws-kpi__value" style={{ color }}>{p.value}</div>
      {p.hint && <div className="ws-kpi__hint">{p.hint}</div>}
    </div>
  );
}

export function Bars({ rows, fmt }: { rows: { label: string; value: number; onClick?: () => void }[]; fmt?: (v: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <div className="ws-muted ws-small">Nothing yet.</div>;
  return (
    <div className="ws-bars">
      {rows.map((r) => (
        <div key={r.label} className="ws-bar" onClick={r.onClick} style={{ cursor: r.onClick ? "pointer" : undefined }}>
          <span className="ws-ellipsis" title={r.label}>{r.label}</span>
          <div className="ws-bar__track"><div className="ws-bar__fill" style={{ width: `${(r.value / max) * 100}%` }} /></div>
          <span className="ws-right ws-mono">{fmt ? fmt(r.value) : num(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Opens an attachment (base64 from the backend) in a new tab, or downloads it. */
export async function openAttachment(id: number, toast: Toaster) {
  const r = await call("inbox_attachment", { attachment_id: id });
  if (!r.ok) { toast(r.error || "Could not open the file.", "bad"); return; }
  const bin = atob(r.data);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: r.mime }));
  const a = document.createElement("a");
  a.href = url;
  if (!/pdf|image/.test(r.mime)) a.download = r.filename;
  else a.target = "_blank";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}
