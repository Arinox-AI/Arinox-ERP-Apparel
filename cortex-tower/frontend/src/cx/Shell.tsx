import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  BarChart3, Bolt, Calendar, ChevronDown, CircleDollarSign, Database, Factory, FileText, Handshake, Home, Inbox,
  Layers, LogOut, Menu, Package, PenLine, RefreshCw, Search, Settings, ShieldCheck, Ship, ShoppingCart,
  Sparkles, Truck, User, Users, Workflow,
} from "lucide-react";
import { call, setToken } from "./api";
import type { R } from "./api";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { Btn, Cell, CxCtx, List, Note, Pill, ReviewSheet, Section, Sheet, Skel, useToast } from "./ui";
import type { Review } from "./ui";
import { DocList, DocSheet, FormSheet } from "./views/Docs";
import { AdminView, ApprovalsView, InquiriesView, ReportRunner, ReportsView, SearchSheet, SyncView, TodayView, TsrView } from "./views/Views";
import "./cx.css";
import { ErrorBoundary } from "../ErrorBoundary";

/* One stroke icon per area, so the rail reads as a set of instruments, not a menu. */
const GROUP_ICON: Record<string, ReactNode> = {
  home: <Home size={15} />, enquire: <Inbox size={15} />, win: <Handshake size={15} />, plan: <Calendar size={15} />,
  materials: <Layers size={15} />, make: <Factory size={15} />, quality: <ShieldCheck size={15} />, ship: <Ship size={15} />,
  analyse: <BarChart3 size={15} />, control: <Settings size={15} />, all_records: <Database size={15} />,
};

/* Per-screen icons for the screens people live in all day. */
const ITEM_ICON: Record<string, ReactNode> = {
  today: <Bolt size={15} />, tna: <Calendar size={15} />, approvals: <ShieldCheck size={15} />, reports: <BarChart3 size={15} />,
  inquiries: <Inbox size={15} />, sync: <Workflow size={15} />, admin: <Users size={15} />, tsr: <Settings size={15} />,
  sales_order: <FileText size={15} />, purchase_order: <ShoppingCart size={15} />, purchase_receipt: <Package size={15} />,
  delivery_note: <Truck size={15} />, quotation: <PenLine size={15} />, customer: <Users size={15} />, item: <Package size={15} />,
  payment_entry: <CircleDollarSign size={15} />, work_order: <Factory size={15} />, job_card: <Factory size={15} />,
};

/** Screens that already exist in the tower and are shown inside this shell. */
const LEGACY = new Set(["overview", "orders", "risks", "wip", "tna", "fabric", "forecast", "actions", "intake", "inbox", "operations", "mail", "activity"]);

export function Shell(props: { me: R; renderLegacy: (key: string) => ReactNode; legacyCounts: Record<string, number>; connected: boolean; onAsk: () => void; legacyRefresh: () => void; summary?: R }) {
  const { me } = props;
  const [nav, setNav] = useState<R[] | null>(null);
  const [navErr, setNavErr] = useState("");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [writeMode, setWriteMode] = useState("");
  const [active, setActive] = useState<string>(() => (location.hash.match(/^#\/([a-z_0-9]+)$/) || [])[1] || "today");
  const [closed, setClosed] = useState<Record<string, boolean>>(() => { try { return JSON.parse(localStorage.getItem("cx_closed") || "{}"); } catch { return {}; } });
  const [docs, setDocs] = useState<{ dt: string; name: string }[]>([]);
  const [form, setForm] = useState<{ dt: string; initial?: R } | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [search, setSearch] = useState(false);
  const [areaNav, setAreaNav] = useState(false);
  const [account, setAccount] = useState(false);
  const [tick, setTick] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const toast = useToast();

  /* nav + badges */
  useEffect(() => {
    call("cx_catalog").then((r) => { if (r.ok) { setNav(r.nav); setWriteMode(r.write_mode); } else setNavErr(r.error || "Could not load the menu."); });
  }, []);
  useEffect(() => { call("cx_nav_counts").then((r) => r.ok && setCounts(r.counts)); }, [tick]);

  const items = useMemo(() => (nav || []).flatMap((g) => g.items.map((i: R) => ({ ...i, group: g.key, groupLabel: g.label }))), [nav]);
  const current = items.find((i) => i.key === active);

  /* routing: the route is state first (a click always works, even where history is blocked), the hash is
     written as a best-effort extra so Back works and links can be shared */
  const go = useCallback((key: string) => {
    if (key === "ask") { props.onAsk(); return; }
    setActive(key); setAreaNav(false); setDocs([]); setForm(null);
    try { if (location.hash !== `#/${key}`) history.pushState(null, "", `#/${key}`); } catch { /* opaque-origin frame */ }
    scroller.current?.scrollTo({ top: 0 });
  }, [props]);
  useEffect(() => {
    const on = () => {
      const m = location.hash.match(/^#\/doc\/([^/]+)\/(.+)$/);
      if (m) { setDocs([{ dt: decodeURIComponent(m[1]), name: decodeURIComponent(m[2]) }]); return; }
      const k = (location.hash.match(/^#\/([a-z_0-9]+)$/) || [])[1];
      if (k) setActive(k);
    };
    on();
    window.addEventListener("popstate", on); window.addEventListener("hashchange", on);
    return () => { window.removeEventListener("popstate", on); window.removeEventListener("hashchange", on); };
  }, []);

  /* ⌘K / Ctrl-K opens search from anywhere, like any operator tool */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearch(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* background sync: while a tab is open, look for ERP-side changes every minute */
  useEffect(() => {
    call("sync_changes");
    const t = window.setInterval(() => { if (document.visibilityState === "visible") call("sync_changes"); }, 60000);
    return () => window.clearInterval(t);
  }, []);

  /* a group the backend marks `collapsed` (the long "All ERP records" list) starts closed */
  const isClosed = (g: R) => (closed[g.key] ?? !!g.collapsed) && !g.items.some((it: R) => it.key === active);
  const toggleGroup = (g: R) => {
    const n = { ...closed, [g.key]: !isClosed(g) };
    setClosed(n);
    try { localStorage.setItem("cx_closed", JSON.stringify(n)); } catch { /* private window */ }
  };
  const syncNow = async () => {
    setSyncing(true);
    const r = await call("sync_changes");
    setSyncing(false);
    setTick((t) => t + 1);
    toast.show(r.ok ? (r.skipped ? "Already syncing" : "Checked the ERP for changes") : r.error || "Could not sync");
  };

  const ctx = useMemo(() => ({
    me, go, tick,
    openDoc: (dt: string, name: string) => setDocs((d) => [...d, { dt, name }]),
    newDoc: (dt: string, initial?: R) => setForm({ dt, initial }),
    toast: toast.show, review: (r: Review) => setReview(r),
    refresh: () => { setTick((t) => t + 1); props.legacyRefresh(); },
  }), [me, go, tick, toast.show, props]);

  const badge = (it: R): number => (it.kind === "doc" ? counts[it.key] || 0 : props.legacyCounts[it.key] || 0);

  /* ── content ── */
  let body: ReactNode;
  if (!nav && !navErr) body = <><Skel h={26} w="34%" /><Skel h={92} mt={16} /><Skel h={190} mt={12} /></>;
  else if (navErr) body = <Note tone="bad">{navErr}</Note>;
  else if (!current && active !== "today") body = <Note tone="warn">This screen isn’t available to your role.</Note>;
  else if (active === "today") body = <TodayView summary={{ ...(props.summary || {}), write_mode: writeMode }} />;
  else if (current?.kind === "doc") body = <DocList key={current.doctype} doctype={current.doctype} title={current.label} />;
  else if (current?.kind === "report") body = <ReportRunner key={current.report} name={current.report} />;
  else if (active === "reports") body = <ReportsView />;
  else if (active === "inquiries") body = <InquiriesView />;
  else if (active === "approvals") body = <ApprovalsView />;
  else if (active === "sync") body = <SyncView />;
  else if (active === "tsr") body = <TsrView />;
  else if (active === "admin") body = <AdminView />;
  else if (LEGACY.has(active)) body = <div className="cx-legacy">{props.renderLegacy(active)}</div>;
  else body = <Note tone="warn">Unknown screen.</Note>;

  const signOut = async () => { await call("kogo_logout"); setToken(null); location.hash = ""; location.reload(); };
  const initials = (me.name || me.email || "?").split(/[ @.]/).filter(Boolean).slice(0, 2).map((s: string) => s[0].toUpperCase()).join("");
  const ic = (it: R) => ITEM_ICON[it.key] || GROUP_ICON[it.group] || <FileText size={15} />;

  /* the rail is rendered twice: fixed on desktop, inside a drawer on small screens */
  const railBody = (
    <>
      <div className="cx-side__head"><span className="cx-side__label">Work areas</span>
        <button className="cx-icon-btn" style={{ width: 26, height: 26 }} onClick={() => setAreaNav(false)} aria-label="Close menu"><Menu size={14} /></button>
      </div>
      <nav className="cx-side__nav" aria-label="Main">
        {(nav || []).map((g) => (
          <div key={g.key} className={`cx-group${isClosed(g) ? " is-closed" : ""}`}>
            <button className="cx-group__head" onClick={() => toggleGroup(g)} aria-expanded={!isClosed(g)}>
              <span>{g.label}</span>{g.key === "all_records" && <span className="cx-group__count">{g.items.length}</span>}<ChevronDown size={13} />
            </button>
            <div className="cx-group__items"><div className="cx-group__inner">
              {g.items.map((it: R) => (
                <button key={it.key} className={`cx-item${active === it.key ? " is-active" : ""}`} onClick={() => go(it.key)} title={it.label} aria-current={active === it.key ? "page" : undefined}>
                  <span className="cx-item__ico">{ic({ ...it, group: g.key })}</span>
                  <span className="cx-item__label">{it.label}</span>
                  {badge(it) > 0 && <span className={`cx-badge-n${it.kind === "doc" ? " is-quiet" : ""}`}>{badge(it) > 99 ? "99+" : badge(it)}</span>}
                </button>))}
            </div></div>
          </div>))}
      </nav>
    </>
  );

  return (
    <CxCtx.Provider value={ctx}>
      <div className="cx-app">
        {/* ── command bar ── */}
        <header className="cx-bar">
          <div className="cx-bar__brand">
            <button className="cx-icon-btn cx-menu-btn" onClick={() => setAreaNav(true)} aria-label="Open work areas"><Menu size={16} /></button>
            <div className="cx-mark">CT</div>
            <div className="cx-wordmark"><span className="cx-wordmark__t">Cortex Tower</span><span className="cx-wordmark__s">ERP command centre</span></div>
          </div>

          <div className="cx-bar__crumb">
            {current?.groupLabel ? <><span>{current.groupLabel}</span><span className="cx-sep">/</span></> : null}
            <b>{current?.label || "Today"}</b>
          </div>

          <span className="cx-bar__sp" />

          <button className="cx-cmd" onClick={() => setSearch(true)} aria-label="Search records">
            <Search size={14} /><span className="cx-cmd__hint" style={{ flex: 1, textAlign: "left" }}>Search orders, styles, POs…</span><span className="cx-kbd">⌘K</span>
          </button>

          <span className={`cx-status${props.connected ? "" : " is-down"}`} title={props.connected ? "The ERP answered the last check" : "The ERP did not answer the last check"}>
            <i /><span>{props.connected ? "ERP live" : "ERP offline"}</span>
          </span>

          <Button variant="ghost" size="icon" className="h-8 w-8 text-[#4b5563]" onClick={syncNow} aria-label="Sync with the ERP" title="Sync with the ERP">
            {syncing ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          </Button>

          <Button size="sm" className="h-8 gap-1.5 px-3" onClick={props.onAsk}><Sparkles size={14} /> Ask Cortex</Button>
        </header>

        {/* ── rail (desktop) ── */}
        <aside className="cx-side" aria-label="Work areas">
          {railBody}
          <div className="cx-side__foot">
            <button className="cx-avatar" style={{ border: "1px solid var(--cx-line-2)", cursor: "pointer" }} onClick={() => setAccount(true)} aria-label="Account">{initials}</button>
            <div className="cx-who" style={{ minWidth: 0, flex: 1 }}>
              <b>{me.name || me.email}</b>
              <span className={`cx-live${props.connected ? "" : " is-down"}`}><i />{props.connected ? "Connected" : "Offline"}</span>
            </div>
          </div>
        </aside>

        {/* ── work surface ── */}
        <main className="cx-main">
          <div className="cx-scroll" ref={scroller}><div className="cx-page" key={active}><ErrorBoundary scope={current?.label || "this"} resetKey={active}>{body}</ErrorBoundary></div></div>
        </main>
      </div>

      {/* ── rail (small screens) ── */}
      {areaNav && (
        <div className="cx-drawer" role="dialog" aria-modal="true" aria-label="Work areas">
          <div className="cx-drawer__scrim" onClick={() => setAreaNav(false)} />
          <div className="cx-drawer__panel">
            <div style={{ padding: "14px 12px 6px", display: "flex", alignItems: "center", gap: 10 }}>
              <div className="cx-mark">CT</div>
              <div className="cx-wordmark"><span className="cx-wordmark__t">Cortex Tower</span><span className="cx-wordmark__s">ERP command centre</span></div>
            </div>
            {railBody}
            <div className="cx-side__foot">
              <button className="cx-avatar" onClick={() => { setAreaNav(false); setAccount(true); }} aria-label="Account">{initials}</button>
              <div className="cx-who" style={{ minWidth: 0, flex: 1 }}><b>{me.name || me.email}</b><span className={`cx-live${props.connected ? "" : " is-down"}`}><i />{props.connected ? "Connected" : "Offline"}</span></div>
            </div>
          </div>
        </div>
      )}

      {account && <Sheet title={me.name || me.email} sub={me.email} onClose={() => setAccount(false)} short>
        <List>
          <Cell title="Role" value={me.roles?.length ? me.roles.join(", ") : "None yet"} />
          <Cell title="Changes to the ERP" value={<Pill tone={writeMode === "off" ? "red" : writeMode === "all" ? "green" : "orange"}>{writeMode === "off" ? "Off" : writeMode === "all" ? "On" : writeMode === "draft" ? "Drafts only" : writeMode || "…"}</Pill>} />
          <Cell title="ERP" value={props.connected ? "Connected" : "Not reachable"} />
        </List>
        {!me.roles?.length && <Note tone="warn">You don’t have a role yet, so you can look but not change anything. Ask an administrator.</Note>}
        <div className="cx-mt"><Btn kind="danger" block onClick={signOut}><LogOut size={15} /> Sign out</Btn></div>
      </Sheet>}

      {search && <SearchSheet onClose={() => setSearch(false)} />}
      {docs.length > 0 && <DocSheet key={docs.length + docs[docs.length - 1].name} doctype={docs[docs.length - 1].dt} name={docs[docs.length - 1].name}
        onClose={() => { setDocs((d) => d.slice(0, -1)); if (location.hash.startsWith("#/doc/")) { try { history.replaceState(null, "", `#/${active}`); } catch { /* opaque-origin frame */ } } }} />}
      {form && <FormSheet doctype={form.dt} initial={form.initial} onClose={() => setForm(null)}
        onSaved={(doc) => { setForm(null); setTick((t) => t + 1); if (doc?.name) setDocs((d) => [...d, { dt: form.dt, name: doc.name }]); }} />}
      {review && <ReviewSheet review={review} toast={toast.show} onClose={() => { setReview(null); setTick((t) => t + 1); }} />}
      {toast.node}
    </CxCtx.Provider>
  );
}
