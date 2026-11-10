import { LayoutDashboard, ShieldAlert, ListChecks, BarChart3, TrendingUp, History, RefreshCw, Package, Coins, Mail, Inbox, CalendarClock, ChevronsLeft, ChevronsRight, ScanLine, GanttChartSquare, Tag } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Connection, View } from "../types";
import { fmtTime } from "../types";

/* Group order requested: 1 Monitor · 2 Plan · 3 Analyse · 4 Act (· Audit last). */
const NAV: { id: View; label: string; icon: LucideIcon; group: string }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, group: "Monitor" },
  { id: "orders", label: "Order book", icon: Package, group: "Monitor" },
  { id: "risks", label: "Risks", icon: ShieldAlert, group: "Monitor" },
  { id: "wip", label: "WIP plan", icon: GanttChartSquare, group: "Plan" },
  { id: "tna", label: "TnA Calendar", icon: CalendarClock, group: "Plan" },
  { id: "fabric", label: "Fabric price check", icon: Coins, group: "Analyse" },
  { id: "forecast", label: "Forecast", icon: TrendingUp, group: "Analyse" },
  { id: "actions", label: "Recommended actions", icon: ListChecks, group: "Act" },
  { id: "intake", label: "Order intake", icon: ScanLine, group: "Act" },
  { id: "enquiries", label: "Buyer enquiries", icon: Tag, group: "Act" },
  { id: "inbox", label: "Inbox", icon: Inbox, group: "Act" },
  { id: "operations", label: "Operations", icon: BarChart3, group: "Act" },
  { id: "mail", label: "Outbound Mail", icon: Mail, group: "Act" },
  { id: "activity", label: "Activity", icon: History, group: "Audit" },
];

export function Sidebar(props: {
  view: View;
  setView: (v: View) => void;
  counts: { risks: number; critical: number; actions: number; activity: number; orders: number; fabric: number; inbox: number; intake?: number };
  connection?: Connection;
  generatedAt?: string;
  refreshing: boolean;
  onRefresh: () => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}) {
  const { view, setView, counts, connection, generatedAt, refreshing, onRefresh, collapsed, onToggleCollapse } = props;
  const down = !!connection && !connection.connected;

  const countFor = (id: View) => {
    if (id === "tna") return 0;
    if (id === "risks") return counts.risks;
    if (id === "actions") return counts.actions;
    if (id === "activity") return counts.activity;
    if (id === "orders") return counts.orders;
    if (id === "fabric") return counts.fabric;
    if (id === "inbox") return counts.inbox;
    if (id === "intake") return counts.intake || 0;
    return 0;
  };

  let lastGroup = "";

  return (
    <aside className={`sidebar${collapsed ? " is-collapsed" : ""}`}>
      <div className="sidebar__brand">
        <div className="sidebar__mark" title="Apparel Control Tower">AT</div>
        {!collapsed && (
          <div style={{ minWidth: 0 }}>
            <div className="sidebar__title">Apparel Control Tower</div>
            <div className="sidebar__sub">Live operations · KOGO ERP</div>
          </div>
        )}
        <button
          className="sidebar__collapse"
          onClick={onToggleCollapse}
          title={collapsed ? "Expand menu" : "Collapse menu"}
          aria-label={collapsed ? "Expand menu" : "Collapse menu"}
        >
          {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
        </button>
      </div>

      <nav className="sidebar__nav">
        {NAV.map((item) => {
          const Icon = item.icon;
          const showGroup = item.group !== lastGroup;
          lastGroup = item.group;
          const n = countFor(item.id);
          const critical = (item.id === "risks" && counts.critical > 0) || (item.id === "inbox" && counts.critical > 0) || (item.id === "fabric" && counts.critical > 0);
          return (
            <div key={item.id}>
              {showGroup && !collapsed && <div className="sidebar__section">{item.group}</div>}
              {showGroup && collapsed && lastGroup !== "Monitor" && <div className="sidebar__sep" />}
              <button
                className={`nav-item${view === item.id ? " is-active" : ""}`}
                onClick={() => setView(item.id)}
                title={collapsed ? item.label : undefined}
                aria-current={view === item.id ? "page" : undefined}
              >
                <Icon size={16} />
                {!collapsed && (
                  <span className="nav-item__label" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
                )}
                {!collapsed && n > 0 && (
                  <span className={`nav-item__count${critical ? " is-critical" : ""}`}>{n}</span>
                )}
                {collapsed && n > 0 && <span className={`nav-dot${critical ? " is-critical" : ""}`} />}
              </button>
            </div>
          );
        })}
      </nav>

      <div className="sidebar__foot">
        <div className={`conn${down ? " is-down" : ""}`} title={collapsed ? (down ? connection?.error || "ERP issue" : "Live — KOGO ERP") : undefined}>
          <span className="conn__dot" />
          {!collapsed && (
            <div style={{ minWidth: 0 }}>
              <div className="conn__label">{down ? "ERP connection issue" : "Live — KOGO ERP"}</div>
              <div className="conn__meta" title="frontend build">build 2026-11-03.5</div>
              <div className="conn__meta">
                {down ? connection?.error || "unavailable" : `KOGO ERP connected · refreshed ${fmtTime(generatedAt || "") || "now"}`}
              </div>
            </div>
          )}
        </div>
        <button className="btn btn--sm" style={{ width: "100%", marginTop: 10 }} onClick={onRefresh} disabled={refreshing} title="Refresh data">
          <RefreshCw size={13} className={refreshing ? "spin" : undefined} />
          {!collapsed && (refreshing ? "Refreshing…" : "Refresh data")}
        </button>
      </div>
    </aside>
  );
}
