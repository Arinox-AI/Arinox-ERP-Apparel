import { useState } from "react";
import { Bell, CalendarClock, RefreshCw, Settings, LayoutGrid, Kanban, CalendarDays, Layers, FileStack, History, ArrowUpRight, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import SourceBadge from "./SourceBadge";
import ApiStatusBadge, { type ApiStatus } from "./ApiStatusBadge";
import { todayISO } from "../lib/format";
import type { Source } from "../types";

export type View = "plan" | "board" | "calendar" | "program" | "template" | "activity";

const NAV: { id: View; label: string; icon: any }[] = [
  { id: "plan", label: "Plan", icon: LayoutGrid },
  { id: "board", label: "Board", icon: Kanban },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "program", label: "Program", icon: Layers },
];

const GEAR: { id: View; label: string; icon: any }[] = [
  { id: "template", label: "Plan template", icon: FileStack },
  { id: "activity", label: "Change log", icon: History },
];

export interface TopBarProps {
  view: View;
  onNav: (v: View) => void;
  orderLabel: string;
  calendars: string[];
  calendarId: string;
  onCalendarChange: (id: string) => void;
  asOf: string;
  onAsOfChange: (v: string) => void;
  asOfPinned?: boolean;
  onResetAsOf?: () => void;
  source: Source | null;
  apiStatus: ApiStatus;
  loading: boolean;
  onRefresh: () => void;
  pendingCount: number;
  onOpenInbox: () => void;
  towerUrl?: string | null;
  railsOpen?: boolean;
  onToggleRails?: () => void;
}

export default function TopBar({
  view, onNav, orderLabel, calendars, calendarId, onCalendarChange,
  asOf, onAsOfChange, source, apiStatus, loading, onRefresh, pendingCount, onOpenInbox, towerUrl,
  railsOpen = true, onToggleRails, asOfPinned = false, onResetAsOf,
}: TopBarProps) {
  const [gearOpen, setGearOpen] = useState(false);
  const [advOpen, setAdvOpen] = useState(false);

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">
          <div className="brand-mark">TnA</div>
          <div>
            <div className="brand-title">Cortex TnA Calendar</div>
            <div className="brand-sub">Time &amp; Action · backward from ship date</div>
          </div>
        </div>

        <nav className="topnav" role="tablist" aria-label="Views">
          {NAV.map((n) => {
            const Icon = n.icon;
            return (
              <button key={n.id} role="tab" aria-selected={view === n.id}
                className={`topnav-btn${view === n.id ? " active" : ""}`} onClick={() => onNav(n.id)}>
                <Icon size={15} /> {n.label}
              </button>
            );
          })}
        </nav>

        <div className="topbar-controls">
          {orderLabel && <span className="topbar-order mono" title="Current order">{orderLabel}</span>}

          {towerUrl && (
            <a className="tower-jump" href={towerUrl} target="_blank" rel="noreferrer"
               title="Open the Apparel Control Tower">
              Cortex Tower <ArrowUpRight size={14} />
            </a>
          )}

          <button className="icon-btn bell" onClick={onOpenInbox} title="New orders & notifications" aria-label="Notifications">
            <Bell size={17} />
            {pendingCount > 0 && <span className="bell-badge">{pendingCount}</span>}
          </button>

          {onToggleRails && (
            <button
              className={`icon-btn${railsOpen ? "" : " is-off"}`}
              onClick={onToggleRails}
              title={railsOpen ? "Hide the side panels" : "Show the side panels"}
              aria-label={railsOpen ? "Hide side panels" : "Show side panels"}
              aria-pressed={railsOpen}
            >
              {railsOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
            </button>
          )}

          <div className="adv">
            <button className="icon-btn" onClick={() => setAdvOpen((v) => !v)} title="Today, calendar & as-of">
              <CalendarClock size={17} />
            </button>
            {advOpen && (
              <div className="adv-pop" onMouseLeave={() => setAdvOpen(false)}>
                <label className="field">
                  <span>As of</span>
                  <input type="date" className="input" value={asOf} onChange={(e) => onAsOfChange(e.target.value || todayISO())} />
                </label>
                <div className="field">
                  <span>Date mode</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="muted" style={{ fontSize: 11, flex: 1 }}>
                      {asOfPinned ? "Pinned — the calendar stays on the date you set." : "Following today — rolls forward automatically."}
                    </span>
                    {asOfPinned && onResetAsOf && (
                      <button className="btn btn-ghost btn-sm" onClick={onResetAsOf}>Follow today</button>
                    )}
                  </div>
                </div>
                <label className="field">
                  <span>Holiday calendar</span>
                  <select className="input" value={calendarId} onChange={(e) => onCalendarChange(e.target.value)}>
                    {(calendars.length ? calendars : [calendarId]).map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
                <div className="muted" style={{ fontSize: 11 }}>Working-day maths uses this calendar. VN is the factory.</div>
              </div>
            )}
          </div>

          <button className="icon-btn" onClick={onRefresh} disabled={loading} title="Refresh from ERP">
            <RefreshCw size={17} className={loading ? "spin" : ""} />
          </button>

          <SourceBadge source={source} />
          <ApiStatusBadge status={apiStatus} />

          <div className="adv">
            <button className="icon-btn" onClick={() => setGearOpen((v) => !v)} title="More" aria-label="More">
              <Settings size={17} />
            </button>
            {gearOpen && (
              <div className="gear-menu" onMouseLeave={() => setGearOpen(false)}>
                {GEAR.map((g) => {
                  const Icon = g.icon;
                  return (
                    <button key={g.id} className={`gear-item${view === g.id ? " active" : ""}`}
                      onClick={() => { onNav(g.id); setGearOpen(false); }}>
                      <Icon size={15} /> {g.label}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
