import React from "react";
import { Info, X } from "lucide-react";

/* ── Card ─────────────────────────────────────────────────────────────────── */
export function Card(props: {
  title?: React.ReactNode;
  sub?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  flush?: boolean;
  style?: React.CSSProperties;
}) {
  const { title, sub, actions, children, flush, style } = props;
  return (
    <section className="card" style={style}>
      {(title || actions) && (
        <header className="card__head">
          <div style={{ minWidth: 0 }}>
            {title && <div className="card__title">{title}</div>}
            {sub && <div className="card__sub">{sub}</div>}
          </div>
          {actions && <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>{actions}</div>}
        </header>
      )}
      <div className={flush ? "card__body card__body--flush" : "card__body"}>{children}</div>
    </section>
  );
}

/* ── Empty / zero state ───────────────────────────────────────────────────── */
export function Empty(props: { icon?: React.ReactNode; title: string; hint?: string; good?: boolean }) {
  const { icon, title, hint, good } = props;
  return (
    <div className={`empty${good ? " empty--good" : ""}`}>
      <div className="empty__icon">{icon ?? "—"}</div>
      <div style={{ fontWeight: 600, color: "var(--text-secondary)", marginBottom: 2 }}>{title}</div>
      {hint && <div style={{ fontSize: 12 }}>{hint}</div>}
    </div>
  );
}

/* ── Skeleton ─────────────────────────────────────────────────────────────── */
export function Skel({ h = 14, w = "100%", r = 6, style }: { h?: number | string; w?: number | string; r?: number; style?: React.CSSProperties }) {
  return <div className="skel" style={{ height: h, width: w, borderRadius: r, ...style }} />;
}

/* ── Drawer (progressive disclosure) ──────────────────────────────────────── */
export function Drawer(props: {
  onClose: () => void;
  title: React.ReactNode;
  sub?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  const { onClose, title, sub, children, footer, wide } = props;
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className={`drawer${wide ? " drawer--wide" : ""}`} role="dialog" aria-modal="true">
        <div className="drawer__head">
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 700, lineHeight: 1.35 }}>{title}</div>
            {sub && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
          </div>
          <button className="btn btn--ghost btn--icon" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="drawer__body">{children}</div>
        {footer && <div className="drawer__foot">{footer}</div>}
      </aside>
    </>
  );
}

/* ── Modal shell ──────────────────────────────────────────────────────────── */
export function Modal(props: { onClose: () => void; children: React.ReactNode; width?: number }) {
  const { onClose, children, width = 560 } = props;
  return (
    <div className="modal" style={{ background: "rgba(15,42,74,0.4)" }} onClick={onClose}>
      <div className="modal__panel" style={{ maxWidth: width }} onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

/* ── Key/value list ───────────────────────────────────────────────────────── */
export function KV({ items }: { items: { k: string; v: React.ReactNode }[] }) {
  if (!items.length) return null;
  return (
    <div className="kv">
      {items.map((it) => (
        <React.Fragment key={it.k}>
          <div className="kv__k">{it.k}</div>
          <div className="kv__v">{it.v}</div>
        </React.Fragment>
      ))}
    </div>
  );
}

/* ── Section heading inside a page ────────────────────────────────────────── */
export function PageSection(props: { title: string; hint?: string; actions?: React.ReactNode; children: React.ReactNode }) {
  const { title, hint, actions, children } = props;
  return (
    <section style={{ marginTop: 22 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 12, marginBottom: 10 }}>
        <div>
          <h2 style={{ fontSize: 14.5, fontWeight: 700 }}>{title}</h2>
          {hint && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 1 }}>{hint}</div>}
        </div>
        {actions && <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>{actions}</div>}
      </div>
      {children}
    </section>
  );
}

/* ── Info strip — one line telling you what the page is ───────────────────── */
export function InfoStrip(props: { children: React.ReactNode; chips?: React.ReactNode }) {
  const { children, chips } = props;
  return (
    <div className="info-strip">
      <Info size={13} style={{ flex: "0 0 13px", marginTop: 1, color: "var(--text-muted)" }} />
      <div style={{ minWidth: 0, lineHeight: 1.5 }}>{children}</div>
      {chips && (
        <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", flex: "0 0 auto" }}>
          {chips}
        </div>
      )}
    </div>
  );
}
