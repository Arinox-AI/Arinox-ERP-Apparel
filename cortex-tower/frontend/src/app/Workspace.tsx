import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity, AlertTriangle, BarChart3, Briefcase, Calculator, Calendar, ChevronDown, Database, Factory, FileInput, Gauge, Inbox as InboxIcon,
  LayoutDashboard, LineChart, ListChecks, LogOut, Menu, Package, Receipt, Scissors, Search, Truck, Settings as SettingsIcon, Sparkles, Users,
} from "lucide-react";
import { call, setToken } from "../cx/api";
import type { R } from "../cx/api";
import { CxCtx, ReviewSheet, useToast as useCxToast } from "../cx/ui";
import type { Review } from "../cx/ui";
import { DocList, DocSheet, FormSheet } from "../cx/views/Docs";
import { ReportRunner, ReportsView, SearchSheet } from "../cx/views/Views";
import { ErrorBoundary } from "../ErrorBoundary";
import { Btn, Card, Head, Loading, Note, ToastHost } from "./kit";
import { Dashboard } from "./Dashboard";
import { Inbox } from "./Inbox";
import { Deals } from "./Deals";
import { Costing } from "./Costing";
import { DealPage } from "./DealPage";
import { OrderBook, OrderPage } from "./OrderPage";
import { ProductionBoard } from "./ProductionBoard";
import { Customers } from "./Customers";
import { Settings } from "./Settings";

const HIDDEN_MORE = new Set(["risks", "forecast", "fabric", "overview"]); // see the comment in MORE

type Item = { key: string; label: string; icon: ReactNode; count?: number; quiet?: boolean };
const MORE: Item[] = [
  { key: "more/intake", label: "Order intake (POs)", icon: <FileInput size={16} /> },
  // Risks, Forecast, Fabric price check and Order risk overview are hidden (HIDDEN_MORE): they read stock BOM / Work Order and
  // retired production sources, so they showed artefacts. Components and routes stay; restore when the agent layer or the costing/BOM wiring replaces them.
  { key: "more/actions", label: "Recommended actions", icon: <ListChecks size={16} /> },
  { key: "more/operations", label: "Operations charts", icon: <Gauge size={16} /> },
  { key: "more/activity", label: "Tower activity", icon: <Activity size={16} /> },
];
const TITLES: Record<string, string> = {
  dashboard: "Dashboard", inbox: "Inbox", deals: "Deals", costing: "Costing", customers: "Customers", orders: "Orders", tna: "T&A calendar", board: "Production board",
  records: "ERP records", reports: "Reports", settings: "Settings", more: "More",
};
/** legacy screens that need the big dashboard read; it is only fetched when one of them opens */
export const NEEDS_DASH = new Set(["overview", "orders_book", "risks", "actions", "operations", "forecast", "activity"]);

function parse(): string[] {
  const h = location.hash.replace(/^#\/?/, "");
  return h ? h.split("/").map((p) => { try { return decodeURIComponent(p); } catch { return p; } }) : ["dashboard"];
}

/* Some hosts render the app inside a frame whose document has an opaque origin (srcdoc / blob / data
   URL). There `history.pushState` throws a SecurityError. Routing must therefore NEVER depend on the
   URL: the route is React state, and the hash is written only as a best-effort extra. */
let hashWritable = true;
function writeHash(h: string) {
  if (!hashWritable) return;
  try { if (location.hash !== h) history.pushState(null, "", h); } catch { hashWritable = false; }
}

export function Workspace(props: { me: R; renderLegacy: (key: string) => ReactNode; onLegacy: (key: string) => void; onAsk: () => void; connected: boolean }) {
  const { me } = props;
  const [route, setRoute] = useState<string[]>(parse);
  const [navOpen, setNavOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(() => { try { return localStorage.getItem("ws_more") === "1"; } catch { return false; } });
  const [inboxCounts, setInboxCounts] = useState<R>({});
  const [docs, setDocs] = useState<{ dt: string; name: string }[]>([]);
  const [form, setForm] = useState<{ dt: string; initial?: R } | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [search, setSearch] = useState(false);
  const [account, setAccount] = useState(false);
  const [tick, setTick] = useState(0);
  const cxToast = useCxToast();
  const main = useRef<HTMLDivElement>(null);

  const go = useCallback((path: string) => {
    /* decode each segment: callers pass encodeURIComponent("Tech Pack") and the screens want the real name */
    const parts = path.replace(/^#?\/?/, "").split("/").filter(Boolean)
      .map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
    const next = parts.length ? parts : ["dashboard"];
    setRoute(next); setNavOpen(false); setDocs([]); setForm(null);   /* state first: the click always works */
    writeHash("#/" + next.map((p) => { try { return encodeURIComponent(p); } catch { return p; } }).join("/"));
    main.current?.scrollTo({ top: 0 });
  }, []);
  useEffect(() => {
    const on = () => {
      const m = location.hash.match(/^#\/doc\/([^/]+)\/(.+)$/);
      if (m) { setDocs([{ dt: decodeURIComponent(m[1]), name: decodeURIComponent(m[2]) }]); return; }
      setRoute(parse());
    };
    window.addEventListener("popstate", on); window.addEventListener("hashchange", on);
    return () => { window.removeEventListener("popstate", on); window.removeEventListener("hashchange", on); };
  }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearch(true); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  /* the inbox badge, and ERP-side changes, while a tab is open */
  useEffect(() => {
    const load = () => { void call("inbox_threads", { limit: 1 }).then((r) => r.ok && setInboxCounts(r.counts || {})); };
    load(); void call("sync_changes");
    const t = window.setInterval(() => { if (document.visibilityState === "visible") { load(); void call("sync_changes"); } }, 120000);
    return () => window.clearInterval(t);
  }, []);
  const [top, sub] = route;
  useEffect(() => { if (top === "more" && sub && HIDDEN_MORE.has(sub)) { go("dashboard"); return; } if (top === "more" && sub) props.onLegacy(sub); if (top === "tna") props.onLegacy("tna"); }, [top, sub]); // eslint-disable-line react-hooks/exhaustive-deps

  const ctx = useMemo(() => ({
    me, tick,
    go: (key: string) => go(key === "today" || HIDDEN_MORE.has(key) ? "dashboard" : ["tna", "reports", "approvals", "admin", "sync"].includes(key) ? (key === "approvals" ? "settings/approvals" : key === "admin" ? "settings/users" : key === "sync" ? "settings/sync" : key) : `more/${key}`),
    openDoc: (dt: string, name: string) => setDocs((d) => [...d, { dt, name }]),
    newDoc: (dt: string, initial?: R) => setForm({ dt, initial }),
    toast: cxToast.show, review: (r: Review) => setReview(r),
    refresh: () => setTick((t) => t + 1),
  }), [me, tick, go, cxToast.show]);

  const work: Item[] = [
    { key: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={16} /> },
    { key: "inbox", label: "Inbox", icon: <InboxIcon size={16} />, count: inboxCounts.needs_reply || 0 },
    { key: "deals", label: "Deals", icon: <Briefcase size={16} /> },
    { key: "costing", label: "Costing", icon: <Calculator size={16} /> },
    { key: "customers", label: "Customers", icon: <Users size={16} /> },
  ];
  const ops: Item[] = [
    { key: "orders", label: "Order book", icon: <Package size={16} /> },
    { key: "board", label: "Production board", icon: <Factory size={16} /> },
    { key: "tna", label: "T&A calendar", icon: <Calendar size={16} /> },
    { key: "records/Shipment", label: "Shipments", icon: <Truck size={16} /> },
    { key: "records/Sales Invoice", label: "Receivables", icon: <Receipt size={16} /> },
    { key: "records", label: "ERP records", icon: <Database size={16} /> },
    { key: "reports", label: "Reports", icon: <BarChart3 size={16} /> },
  ];
  const active = top === "more" ? `more/${sub}` : top === "records" && sub ? `records/${sub}` : top;
  const navBtn = (it: Item) => (
    <button key={it.key} className={`ws-nav__item${active === it.key ? " is-on" : ""}`} onClick={() => go(it.key)} aria-current={active === it.key ? "page" : undefined}>
      {it.icon}<span>{it.label}</span>{it.count ? <span className={`ws-count${it.quiet ? " is-quiet" : ""}`}>{it.count > 99 ? "99+" : it.count}</span> : null}
    </button>
  );

  let body: ReactNode;
  let full = false;
  if (top === "dashboard") body = <Dashboard go={go} me={me} />;
  else if (top === "inbox") { full = true; body = <Inbox go={go} threadKey={sub} onCounts={setInboxCounts} />; }
  else if (top === "deals" && sub) body = <DealPage key={sub} id={Number(sub)} go={go} />;
  else if (top === "deals") body = <Deals go={go} />;
  else if (top === "costing") body = <Costing go={go} dealId={sub} styleKey={route[2]} />;
  else if (top === "customers") body = <Customers go={go} name={sub} />;
  else if (top === "orders" && sub) body = <OrderPage key={sub} so={sub} step={route[2]} go={go} />;
  else if (top === "orders") body = <OrderBook go={go} />;
  else if (top === "board") body = <ProductionBoard go={go} />;
  else if (top === "tna") { full = true; body = <div className="ws-tna">{props.renderLegacy("tna")}</div>; }
  else if (top === "records") body = <Records go={go} doctype={sub} />;
  else if (top === "reports") body = <div className="ws-page"><div className="cx-legacy">{sub ? <><Btn kind="plain" sm onClick={() => go("reports")}>← All reports</Btn><ReportRunner key={sub} name={sub} /></> : <ReportsView />}</div></div>;
  else if (top === "settings") body = <Settings tab={sub} go={go} />;
  else if (top === "more" && sub && HIDDEN_MORE.has(sub)) body = <div className="ws-page"><Note tone="warn">This screen is hidden for now. <Btn kind="plain" sm onClick={() => go("dashboard")}>Go to the dashboard</Btn></Note></div>;
  else if (top === "more" && sub) body = <div className="ws-legacy cx-legacy">{props.renderLegacy(sub)}</div>;
  else body = <div className="ws-page"><Note tone="warn">This page does not exist. <Btn kind="plain" sm onClick={() => go("dashboard")}>Go to the dashboard</Btn></Note></div>;

  const crumb = top === "orders" && sub ? "Orders" : top === "deals" && sub ? "Deals" : top === "costing" && sub ? "Costing" : top === "inbox" && sub ? "Inbox" : top === "more" ? "More" : "";
  const title = top === "orders" && sub ? sub : top === "more" ? (MORE.find((m) => m.key === `more/${sub}`)?.label || "More") : top === "deals" && sub ? `Deal #${sub}` : top === "inbox" && sub ? "Conversation" : TITLES[top] || "";
  const initials = (me.name || me.email || "?").split(/[ @.]/).filter(Boolean).slice(0, 2).map((s: string) => s[0].toUpperCase()).join("");
  const signOut = async () => { await call("kogo_logout"); setToken(null); location.hash = ""; location.reload(); };

  return (
    <CxCtx.Provider value={ctx}>
      <ToastHost>
        <div className={`ws ws-app${navOpen ? " is-nav" : ""}`}>
          <aside className="ws-side" aria-label="Main navigation">
            <div className="ws-brand"><div className="ws-mark">CT</div><div><b>Cortex Tower</b><span>Apparel operations</span></div></div>
            <nav className="ws-nav">
              <div className="ws-nav__label">Work</div>{work.map(navBtn)}
              <div className="ws-nav__label">Orders</div>{ops.map(navBtn)}
              <button className="ws-nav__label" onClick={() => { const n = !moreOpen; setMoreOpen(n); try { localStorage.setItem("ws_more", n ? "1" : "0"); } catch { /* */ } }} aria-expanded={moreOpen}>
                More tools <ChevronDown size={13} style={{ transform: moreOpen ? "rotate(180deg)" : undefined }} />
              </button>
              {(moreOpen || top === "more") && MORE.map(navBtn)}
              <div style={{ height: 8 }} />
              {navBtn({ key: "settings", label: "Settings", icon: <SettingsIcon size={16} /> })}
            </nav>
            <div className="ws-side__foot">
              <button className="ws-avatar" onClick={() => setAccount(true)} aria-label="Account">{initials}</button>
              <div style={{ minWidth: 0 }}><b>{me.name || me.email}</b><span><span className={`ws-dot${props.connected ? "" : " is-down"}`} /> {props.connected ? "ERP connected" : "ERP offline"}</span></div>
            </div>
          </aside>
          {navOpen && <div className="ws-scrim" onClick={() => setNavOpen(false)} />}
          <header className="ws-top">
            <button className="ws-btn ws-btn--ghost ws-btn--icon ws-menu-btn" onClick={() => setNavOpen(true)} aria-label="Open navigation"><Menu size={16} /></button>
            {crumb && <span className="ws-top__crumb">{crumb} /</span>}
            <h1>{title}</h1>
            <span className="ws-top__sp" />
            <button className="ws-search" onClick={() => setSearch(true)} aria-label="Search the ERP"><Search size={14} /><span>Search orders, styles, POs…</span><span className="ws-kbd">⌘K</span></button>
            <button className="ws-btn ws-btn--dark" onClick={props.onAsk}><Sparkles size={14} /> Ask</button>
          </header>
          <main className={`ws-main${full ? " is-full" : ""}`} ref={main}>
            <ErrorBoundary scope={title || "this page"} resetKey={route.join("/")}>{body}</ErrorBoundary>
          </main>
        </div>

        {account && <AccountSheet me={me} onClose={() => setAccount(false)} onSignOut={signOut} />}
        {search && <div className="cx-legacy"><SearchSheet onClose={() => setSearch(false)} /></div>}
        {docs.length > 0 && <DocSheet key={docs.length + docs[docs.length - 1].name} doctype={docs[docs.length - 1].dt} name={docs[docs.length - 1].name}
          onClose={() => { setDocs((d) => d.slice(0, -1)); if (location.hash.startsWith("#/doc/")) { try { history.replaceState(null, "", `#/${route.join("/")}`); } catch { /* opaque origin */ } } }} />}
        {form && <FormSheet doctype={form.dt} initial={form.initial} onClose={() => setForm(null)}
          onSaved={(doc) => { setForm(null); setTick((t) => t + 1); if (doc?.name) setDocs((d) => [...d, { dt: form.dt, name: doc.name }]); }} />}
        {review && <ReviewSheet review={review} toast={cxToast.show} onClose={() => { setReview(null); setTick((t) => t + 1); }} />}
        {cxToast.node}
      </ToastHost>
    </CxCtx.Provider>
  );
}

function AccountSheet({ me, onClose, onSignOut }: { me: R; onClose: () => void; onSignOut: () => void }) {
  return (
    <div className="ws ws-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="ws-modal" role="dialog" aria-modal="true" style={{ maxWidth: 420 }}>
        <div className="ws-modal__head"><div><h3>{me.name || me.email}</h3><p>{me.email}</p></div><button className="ws-x" onClick={onClose} aria-label="Close">×</button></div>
        <div className="ws-modal__body">
          <dl className="ws-kv"><dt>Roles</dt><dd>{(me.roles || me.tower_roles || []).join(", ") || "None yet"}</dd><dt>Signed in via</dt><dd>{me.via === "kogo" ? "KOGO" : "Password"}</dd></dl>
          {!(me.roles || me.tower_roles || []).length && <div className="ws-mt"><Note tone="warn">You have no role yet, so you can look but not change anything. Ask an administrator.</Note></div>}
        </div>
        <div className="ws-modal__foot"><Btn kind="danger" onClick={onSignOut}><LogOut size={14} /> Sign out</Btn></div>
      </div>
    </div>
  );
}

/** Every ERP doctype the tower can open, grouped by where it sits in the order flow. */
function Records({ go, doctype }: { go: (p: string) => void; doctype?: string }) {
  const [nav, setNav] = useState<R[] | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { void call("cx_catalog").then((r) => (r.ok ? setNav(r.nav) : setErr(r.error || "Could not load the list."))); }, []);
  if (doctype) return (
    <div className="ws-page">
      <div style={{ marginBottom: 8 }}><Btn kind="plain" sm onClick={() => go("records")}>← All records</Btn></div>
      <div className="cx-legacy"><DocList key={doctype} doctype={doctype} title={doctype} /></div>
    </div>
  );
  const groups = (nav || []).map((g: R): R => ({ ...g, items: g.items.filter((it: R) => it.kind === "doc" && (!q || it.label.toLowerCase().includes(q.toLowerCase()) || it.doctype.toLowerCase().includes(q.toLowerCase()))) }))
    .filter((g) => g.items.length);
  return (
    <div className="ws-page">
      <Head title="ERP records" sub="Open any ERP document type to list, search, create or edit records. Changes go through the same business rules as the ERP."
        acts={<input className="ws-input" style={{ width: 240 }} placeholder="Find a record type" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a record type" />} />
      {err ? <Note tone="bad">{err}</Note> : !nav ? <Loading /> : (
        <div className="ws-grid ws-grid--3">
          {groups.map((g) => (
            <Card key={g.key} title={g.label.replace(/^\d · /, "")} flush>
              {g.items.map((it: R) => (
                <div key={it.key} className="ws-list-row" onClick={() => go(`records/${encodeURIComponent(it.doctype)}`)}>
                  <Database size={14} color="var(--ws-faint)" /><span style={{ flex: 1 }}>{it.label}</span>{it.label !== it.doctype && <span className="ws-small ws-muted">{it.doctype}</span>}
                </div>))}
            </Card>))}
        </div>)}
    </div>
  );
}
