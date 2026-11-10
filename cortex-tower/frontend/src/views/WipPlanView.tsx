/* ── WIP plan — Gantt, calendar, late & recovery, and the planning queue ───────
 *
 * The ERP's own surface for `Cortex WIP` is a list and a child grid: 364 rows, which the client cannot read
 * (2026-11-03). This tab is the working tool:
 *
 *   Gantt            every gate in the window it owns, grouped by order / plant / buyer / department,
 *                    with filters and a "late only" switch
 *   Calendar         every drop-dead on its own day
 *   Late & recovery  what is late, and **how to make the date** — the catch-up arithmetic per SKU
 *                    (PAST / TIGHT / SLACK, the target date of each remaining gate, the spare days)
 *   Queue            orders that are NOT planned yet: the writer only *proposes*, a planner discusses it here
 *                    and then finalises, adjusts or rejects it (mode-gated writes, every act leaves a Comment
 *                    on the ERP record)
 *
 * All numbers come from `get_wip_plan` / `get_wip_thread` and the four actions `wip_comment`, `wip_finalise`,
 * `wip_adjust`, `wip_reject` (backend/wip_plan.py + backend/wip_actions.py).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { callApi } from "../services/api";
import { PlanBoard } from "./WipPlanBoard";
import { Card, Drawer, Empty, Skel } from "../ui";

/* ── types ──────────────────────────────────────────────────────────────────── */
type State = "PAST" | "TIGHT" | "SLACK" | "DONE";
interface Bar {
  milestone: string; department?: string | null; start?: string | null; end?: string | null;
  date?: string | null; actual?: string | null; status?: string | null; planned_status?: string | null;
  implied?: boolean; late_days?: number;
  critical?: boolean; source?: string | null; slack_days?: number | null; window_days?: number | null;
  critical_now?: boolean; marker_only?: boolean;
}
interface Remain { milestone: string; planned?: string | null; target?: string | null; window_days?: number | null;
  slack_days?: number | null; department?: string | null; status?: string | null; late_days?: number | null }
interface Recovery {
  state: State; headline: string; days_late: number; late_gates: string[]; remaining: Remain[];
  required_days: number; days_left?: number; projected_ship: string; ship: string;
  spare_days: number; compression_pct: number; started_from: string;
}
interface Lane {
  wip: string; order?: string | null; buyer?: string | null; plant?: string | null; sku: string;
  size?: string | null; colour?: string | null; shipped_qty?: number; cut_qty?: number; qty: number; status?: string | null; plan_state: "committed" | "proposal";
  stage?: string | null; next_milestone?: string | null; next_due?: string | null; late?: boolean;
  pct: number; ship_date?: string | null; pcd?: string | null; bars: Bar[]; recovery: Recovery;
}
interface PhaseHead { phase: number; name: string; count: number; span_days: number; missed: number; done: number;
  first_offset: number; last_offset: number; gates: string[] }
interface OrderHead {
  wip: string; sales_order?: string | null; buyer?: string | null; plant?: string | null;
  plant_city?: string | null; pcd?: string | null; ship_date?: string | null; status?: string | null;
  qty: number; late: number; next_due?: string | null; skus: number; lead_days?: number;
  plan_state: "committed" | "proposal"; allocation_note?: string | null; proposed_on?: string | null;
  made_qty?: number; shipped_qty?: number; progress_floor?: number; made_pct?: number | null;
  shipped_pct?: number | null; complete?: boolean;
  plan?: any[]; phases?: number[]; missed?: any[]; projected_ship?: string | null; slip_days?: number;
  gates_total?: number; gates_done?: number; gates_missed?: number; gates_unset?: number;
}
interface Chip { date: string; wip: string; order?: string | null; sku: string; milestone: string;
  department?: string | null; status?: string | null; late_days?: number }
interface QueueItem {
  wip?: string | null; order?: string | null; sales_order?: string | null; buyer?: string | null;
  qty: number; ship_date?: string | null; plant?: string | null; status?: string | null;
  plan_state: string; proposed_on?: string | null; allocation_note?: string | null;
  pcd?: string | null; skus?: number; capacity?: { month: string; plant_capacity: number; booked: number } | null;
}
interface Facets { buyers: string[]; plants: string[]; departments: string[]; statuses: string[];
  plan_states: string[]; orders: { wip: string; order?: string | null; buyer?: string | null }[]; skus: string[] }
interface Issue { kind: string; order?: string | null; sku?: string | null; detail: string }
interface WorkingDays { confirmed: boolean; holidays: number; weekly_off: string[]; basis: string;
  lists: { name: string; from?: string | null; to?: string | null; holiday_rows: number; weekly_off?: string | null }[] }
interface Policy { counts: Record<string, number>; bases: string[] }
interface Plan {
  live: boolean; generated_at?: string; today: string; write_mode: string;
  issues?: { rows: Issue[]; counts: Record<string, number>; total: number; basis: string };
  policy?: Policy; working_days?: WorkingDays;
  orders: OrderHead[]; lanes: Lane[]; queue: QueueItem[]; facets: Facets;
  phases?: PhaseHead[]; alerts?: any[]; alert_basis?: string;
  calendar: { months: string[]; chips: Chip[]; departments: string[] };
  summary: { orders: number; skus: number; milestones: number; pcs: number; late: number; done: number;
    pending: number; passed?: number; next_7_days: number; late_skus: number; slips: number; past: number; tight: number;
    queue: number; proposals: number; committed: number; alerts?: number; gates_missed?: number;
    gates_unset?: number; phases?: number;
    capacity: Record<string, { pcs_month: number; city?: string | null; booked: number }> };
  bar_basis?: string;
  connection?: { connected: boolean; error?: string | null };
}
interface ThreadMsg { text: string; by: string; at: string }

/* ── dates & colour ─────────────────────────────────────────────────────────── */
const BUILD = "u8 · 2026-11-03 23:20";
const DAY = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const parse = (s?: string | null) => (s ? new Date(String(s).slice(0, 10) + "T00:00:00") : null);
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const pretty = (s?: string | null) => {
  const d = parse(s);
  return d ? `${String(d.getDate()).padStart(2, "0")} ${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}` : "—";
};
const todayISO = () => iso(new Date());

const RED = "#e0433c", GREEN = "#1f9d55", BLUE = "#2490ef", AMBER = "#c77700", GREY = "#8fa3b8";
const PASSED = "#7d8ea3";
const statusColour = (s?: string | null) =>
  s === "Done" ? GREEN : s === "Late" ? RED : s === "Passed" ? PASSED : s === "Waived" ? "#b6c2d1"
    : s === "In Progress" ? BLUE : GREY;
const stateColour = (s?: State) => (s === "PAST" ? RED : s === "TIGHT" ? AMBER : s === "SLACK" ? GREEN : GREY);
const stateLabel = (s?: State) =>
  s === "PAST" ? "ship date gone" : s === "TIGHT" ? "makeable with compression" : s === "SLACK" ? "on time" : "done";

/* ── atoms ──────────────────────────────────────────────────────────────────── */
function Tile({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "11px 13px", minWidth: 0 }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)" }}>{label}</div>
      <div style={{ fontSize: 21, fontWeight: 700, marginTop: 2, color: tone || "var(--text)" }}>{value}</div>
      {hint ? <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>{hint}</div> : null}
    </div>
  );
}

function Pill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 700,
      padding: "1px 7px", borderRadius: 20, color: tone, background: `${tone}18`, border: `1px solid ${tone}44`, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

const selStyle: React.CSSProperties = { fontSize: 12, padding: "5px 7px", border: "1px solid var(--border)",
  borderRadius: 7, background: "var(--surface)", color: "var(--text)", maxWidth: 190 };
const btn: React.CSSProperties = { fontSize: 12, fontWeight: 600, padding: "5px 11px", border: "1px solid var(--border)",
  borderRadius: 7, background: "var(--surface)", color: "var(--text-secondary)", cursor: "pointer" };

function Legend() {
  const items: [string, string][] = [[GREEN, "done — a document proves it"], [RED, "late"], [AMBER, "inside its window (slack ≤ 0)"], [GREY, "pending"]];
  return (
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 11, color: "var(--text-muted)" }}>
      {items.map(([c, l]) => (
        <span key={l} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 10, height: 10, borderRadius: 3, background: c, display: "inline-block" }} />{l}
        </span>
      ))}
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <i style={{ width: 2, height: 12, background: RED, display: "inline-block" }} />today
      </span>
    </div>
  );
}

/* ── filters ────────────────────────────────────────────────────────────────── */
interface Filter { q: string; buyer: string; plant: string; dept: string; status: string; late: boolean; plan: string; group: string; issues: boolean }
const styleOf = (sku: string) => sku.replace(/-[^-]+$/, "");

function FilterBar({ f, set, plan, count }: { f: Filter; set: (p: Partial<Filter>) => void; plan: Plan; count: number }) {
  return (
    <div style={{ display: "flex", gap: 7, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
      <input className="input input--sm" placeholder="search order / SKU / buyer" value={f.q}
        onChange={(e) => set({ q: e.target.value })} style={{ ...selStyle, minWidth: 210 }} />
      <select style={selStyle} value={plan.facets.orders.some((o) => o.order === f.q) ? f.q : ""}
        onChange={(e) => set({ q: e.target.value })} title="show one order">
        <option value="">All orders</option>
        {plan.facets.orders.map((o) => (
          <option key={o.wip + (o.order || "")} value={o.order || ""}>{o.order} · {o.buyer}</option>
        ))}
      </select>
      <select style={selStyle} value={f.buyer} onChange={(e) => set({ buyer: e.target.value })}>
        <option value="">All buyers</option>
        {plan.facets.buyers.map((b) => <option key={b} value={b}>{b}</option>)}
      </select>
      <select style={selStyle} value={f.plant} onChange={(e) => set({ plant: e.target.value })}>
        <option value="">All plants</option>
        {plan.facets.plants.map((p) => <option key={p} value={p}>{p.replace(/ Plant$/, "")}</option>)}
      </select>
      <select style={selStyle} value={f.dept} onChange={(e) => set({ dept: e.target.value })}>
        <option value="">All departments</option>
        {plan.facets.departments.map((d) => <option key={d} value={d}>{d}</option>)}
      </select>
      <select style={selStyle} value={f.status} onChange={(e) => set({ status: e.target.value })}>
        <option value="">All statuses</option>
        {plan.facets.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <select style={selStyle} value={f.plan} onChange={(e) => set({ plan: e.target.value })}>
        <option value="">Committed + proposed</option>
        <option value="committed">Committed only</option>
        <option value="proposal">Proposals only</option>
      </select>
      <button style={{ ...btn, background: f.late ? `${RED}14` : "var(--surface)", color: f.late ? RED : "var(--text-secondary)", borderColor: f.late ? `${RED}55` : "var(--border)" }}
        onClick={() => set({ late: !f.late })}>
        {f.late ? "● " : "○ "}Late only
      </button>
      <button style={{ ...btn, background: f.issues ? `${AMBER}14` : "var(--surface)", color: f.issues ? AMBER : "var(--text-secondary)", borderColor: f.issues ? `${AMBER}55` : "var(--border)" }}
        onClick={() => set({ issues: !f.issues })} title="rows with a data-quality finding">
        {f.issues ? "● " : "○ "}Issues only
      </button>
      <select style={selStyle} value={f.group} onChange={(e) => set({ group: e.target.value })} title="group the rows by">
        <option value="order">Group: order</option>
        <option value="style">Group: style (size/colour)</option>
        <option value="plant">Group: plant</option>
        <option value="buyer">Group: buyer</option>
        <option value="dept">Group: department</option>
      </select>
      <span style={{ fontSize: 11.5, color: "var(--text-muted)", marginLeft: "auto" }}>{count} lane(s) shown</span>
    </div>
  );
}


/* ── Track — one row per ORDER, read left to right ────────────────────────────
 *
 * The Gantt answers "when". This answers "where is this order", which is the question a merchandiser actually
 * asks. Thirteen stage boxes in process order, and only four states, spelled out:
 *
 *   ✓ green   a document proves it (with the date)
 *   ✓ grey    passed — the factory made the goods, so the gate happened; only the date is unrecorded
 *   ! red     genuinely late — the date has gone and the work is still owed
 *   • outline not reached yet
 *
 * and one plain sentence under it, so nobody has to decode a colour.
 */
const STAGES = ["Lab Dip", "Bulk Fabric Approval", "PP Sample Approval", "Fabric Requisition Placed",
  "Fabric In-House", "Trim Requisition Placed", "Trims In-House", "PP Meeting", "Cutting", "Sewing",
  "Washing", "Final Inspection", "Ship"];
const SHORT: Record<string, string> = {
  "Lab Dip": "Lab dip", "Bulk Fabric Approval": "Fabric appr.", "PP Sample Approval": "PP sample",
  "Fabric Requisition Placed": "Fabric req'd", "Fabric In-House": "Fabric in", "Trim Requisition Placed": "Trim req'd",
  "Trims In-House": "Trims in", "PP Meeting": "PP meeting", Cutting: "Cutting", Sewing: "Sewing",
  Washing: "Washing", "Final Inspection": "Final insp.", Ship: "Ship",
};

function gateOf(lane: Lane, milestone: string): Bar | undefined {
  return lane.bars.find((b) => b.milestone === milestone);
}

/** the worst state across the SKUs of one order, for the order row */
function worstOf(lanes: Lane[], milestone: string): string {
  const statuses = lanes.map((l) => gateOf(l, milestone)?.status || "Pending");
  if (statuses.includes("Late")) return "Late";
  if (statuses.every((s) => s === "Done")) return "Done";
  if (statuses.every((s) => s === "Done" || s === "Passed")) return "Passed";
  if (statuses.includes("Done")) return "Done";
  return "Pending";
}

function stageIcon(status: string) {
  if (status === "Done") return "✓";
  if (status === "Passed") return "✓";
  if (status === "Late") return "!";
  if (status === "Waived") return "–";
  return "·";
}

function Track({ plan, lanes, onOpenOrder }: { plan: Plan; lanes: Lane[]; onOpenOrder: (o: OrderHead) => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const visible = plan.orders.filter((o) => lanes.some((l) => l.wip === o.wip));

  return (
    <Card title="Track — where every order actually is"
      sub="one row per order · thirteen gates in process order · hover a stage for its date · click the row for the SKUs">
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 11, color: "var(--text-muted)", marginBottom: 10 }}>
        <span><b style={{ color: GREEN }}>✓ green</b> — a document proves it</span>
        <span><b style={{ color: PASSED }}>✓ grey</b> — passed: the goods were made, the date is not recorded</span>
        <span><b style={{ color: RED }}>!</b> — late: the date has gone, the work is still owed</span>
        <span><b>·</b> — not reached</span>
      </div>

      {visible.length === 0 ? <Empty title="Nothing matches these filters" hint="Clear a filter above to see the orders." /> : null}

      {visible.map((o) => {
        const mine = lanes.filter((l) => l.wip === o.wip);
        const isOpen = open[o.wip];
        const late = mine.reduce((a, l) => a + l.bars.filter((b) => b.status === "Late").length, 0);
        const made = o.made_pct ?? null, shipped = o.shipped_pct ?? null;
        const sentence = o.complete
          ? `complete — ${Math.round(o.qty).toLocaleString()} pcs made and shipped`
          : made !== null && made >= 99 && shipped !== null && shipped < 99
            ? `made ${Math.round(o.made_qty || 0).toLocaleString()} of ${Math.round(o.qty).toLocaleString()} · not shipped yet${late ? ` · ${late} gate(s) still owed` : ""}`
            : made
              ? `made ${Math.round(o.made_qty || 0).toLocaleString()} of ${Math.round(o.qty).toLocaleString()} (${made}%)`
              : `nothing made yet — ${Math.round(o.qty).toLocaleString()} pcs planned`;
        return (
          <div key={o.wip} style={{ border: "1px solid var(--border)", borderRadius: 10, marginBottom: 8, overflow: "hidden",
            background: late ? `${RED}06` : "var(--surface)" }}>
            <div onClick={() => onOpenOrder(o)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 11px", cursor: "pointer", flexWrap: "wrap" }}>
              <div style={{ minWidth: 190 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700 }}>{o.buyer}</div>
                <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{o.sales_order}</div>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--text-secondary)", minWidth: 120 }}>
                {Math.round(o.qty).toLocaleString()} pcs
                <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{o.skus} SKU · {(o.plant || "no plant").replace(/ Plant$/, "")}</div>
              </div>
              <div style={{ fontSize: 11.5, minWidth: 100 }}>
                ships {pretty(o.ship_date)}
                <div style={{ fontSize: 10.5, color: (o.ship_date || "") < todayISO() && !o.complete ? RED : "var(--text-muted)" }}>
                  {(o.ship_date || "") < todayISO() && !o.complete ? `passed ${Math.abs(Math.round((+new Date(todayISO()) - +new Date(o.ship_date || todayISO())) / DAY))} d ago` : o.complete ? "done" : "ahead"}
                </div>
              </div>
              <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                {late ? <Pill tone={RED}>{late} late</Pill> : o.complete ? <Pill tone={GREEN}>complete</Pill> : <Pill tone={GREEN}>on plan</Pill>}
                <button type="button" style={btn} onClick={(e) => { e.stopPropagation(); setOpen({ ...open, [o.wip]: !isOpen }); }}>
                  {isOpen ? "hide SKUs" : `${o.skus} SKUs`}
                </button>
              </div>
            </div>

            {/* the thirteen gates */}
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${STAGES.length}, minmax(0, 1fr))`, gap: 3, padding: "0 11px 8px" }}>
              {STAGES.map((st) => {
                const status = worstOf(mine, st);
                const b = mine.map((l) => gateOf(l, st)).find(Boolean);
                const col = statusColour(status);
                const tip = `${st} — ${status}${b?.date ? ` · due ${b.date}` : ""}${b?.actual ? ` · done ${b.actual}` : ""
                  }${b?.implied ? " · passed (no document)" : ""}${b?.late_days ? ` · ${b.late_days}d late` : ""} · ${b?.department || ""}`;
                return (
                  <div key={st} title={tip} style={{ border: `1px solid ${status === "Pending" ? "var(--border)" : col + "66"}`,
                    background: status === "Pending" ? "var(--surface)" : `${col}14`, borderRadius: 5, padding: "3px 4px", minWidth: 0 }}>
                    <div style={{ fontSize: 9.5, fontWeight: 700, color: status === "Pending" ? "var(--text-muted)" : col, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {stageIcon(status)} {SHORT[st] || st}
                    </div>
                    <div style={{ fontSize: 9, color: "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {b?.actual ? pretty(b.actual) : b?.date ? pretty(b.date) : "—"}
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ padding: "0 11px 8px", fontSize: 11.5, color: "var(--text-secondary)" }}>{sentence}</div>

            {isOpen ? (
              <div style={{ borderTop: "1px solid var(--border)", background: "var(--surface-sunken)", padding: "6px 11px" }}>
                {mine.map((l) => (
                  <div key={l.sku} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11, padding: "2px 0" }}>
                    <span style={{ minWidth: 150, fontWeight: 600 }}>{l.sku}</span>
                    <span style={{ color: "var(--text-muted)", minWidth: 60 }}>{Math.round(l.qty)} pcs</span>
                    <span style={{ color: "var(--text-muted)", minWidth: 130 }}>
                      {l.recovery.state === "DONE" ? "all gates cleared" : `next: ${l.next_milestone || "—"}`}
                    </span>
                    <span style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                      {l.bars.some((b) => b.status === "Late") ? <Pill tone={RED}>{l.bars.filter((b) => b.status === "Late").length} late</Pill> : null}
                      <Pill tone={stateColour(l.recovery.state)}>{l.recovery.state}</Pill>
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </Card>
  );
}

/* ── the Gantt — the industry conventions a merchandiser already reads ──────
 *
 * A garment T&A board is not a generic Gantt. What planners expect, and what this draws:
 *
 *   · WEEK columns with the calendar week number (`Wk 44`) and the date range, a month band above,
 *     vertical rules on the weeks and a heavier rule on the month — apparel plans in weeks, not in pixels;
 *   · a DIAMOND for a gate (a date somebody has to hit — approval, PP meeting, inspection) and a light BAR
 *     for the window that gate owns (the work that has to happen between two dates);
 *   · OPEN diamond = still to come · FILLED = a document proves it · RED rim = late;
 *   · PLAN vs ACTUAL: when a gate has an `actual`, the diamond it *should* have hit stays hollow and a small
 *     dot sits where it actually happened, joined by a thin rule — so `+3 days` is visible, not a tooltip;
 *   · a vertical TODAY line, and the ship date marked on the order row;
 *   · RAG **with words** (LATE / AT RISK / ON TRACK / DONE) — never colour alone;
 *   · a right-hand column that reads the row out loud: next gate, days to it, what the plan can still take.
 */
function isoWeek(d: Date) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((+t - +y0) / DAY + 1) / 7);
}
function mondayOf(d: Date) {
  const c = new Date(d);
  const day = (c.getDay() + 6) % 7;
  c.setDate(c.getDate() - day);
  c.setHours(0, 0, 0, 0);
  return c;
}

const DEPT_TAG: Record<string, string> = {
  Merchandising: "M", "Fabric Purchase": "F", "Trim Purchase": "T", Quality: "Q",
  "Production Planner": "P", CAD: "C", Accounts: "A",
};

function ragOf(r: Recovery): { label: string; tone: string } {
  if (r.state === "DONE") return { label: "DONE", tone: GREEN };
  if (r.state === "PAST") return { label: "LATE", tone: RED };
  if (r.state === "TIGHT") return { label: "AT RISK", tone: AMBER };
  return { label: "ON TRACK", tone: GREEN };
}

function Gantt({ plan, lanes, f, onOpen }: { plan: Plan; lanes: Lane[]; f: Filter; onOpen: (l: Lane) => void }) {
  const [dense, setDense] = useState<"weeks" | "days">("weeks");
  // px per DAY. Weeks is the industry default (a week column carries `Wk 44` + its date range), so it starts
  // wide enough to read the label; Days is for the fortnight around a cut-off.
  const [dayPx, setDayPx] = useState(6);
  const [shut, setShut] = useState<Record<string, boolean>>({});
  const pxDay = dayPx;
  const weekPx = pxDay * 7;
  const setMode = (m: "weeks" | "days") => { setDense(m); setDayPx(m === "weeks" ? 6 : 2.4); };
  const showRange = weekPx >= 46;

  /* the domain: whole weeks, so a bar never sits half in a column */
  const dom = useMemo(() => {
    const ds: number[] = [];
    lanes.forEach((l) => {
      l.bars.forEach((b) => { const a = parse(b.start), z = parse(b.end); if (a) ds.push(+a); if (z) ds.push(+z); });
      const s = parse(l.ship_date); if (s) ds.push(+s);
    });
    const t = parse(todayISO())!; ds.push(+t);
    const lo = mondayOf(new Date(Math.min(...ds))); lo.setDate(lo.getDate() - 7);
    const hi = mondayOf(new Date(Math.max(...ds))); hi.setDate(hi.getDate() + 14);
    return { lo, hi, days: Math.max(1, (+hi - +lo) / DAY) };
  }, [lanes]);

  const x = (s?: string | null) => { const d = parse(s); return d ? ((+d - +dom.lo) / DAY) * pxDay : null; };
  const width = dom.days * pxDay;
  const todayX = x(todayISO())!;

  const weeks = useMemo(() => {
    const out: { x: number; wk: number; range: string }[] = [];
    for (let i = 0; i < dom.days / 7; i++) {
      const d = new Date(dom.lo); d.setDate(d.getDate() + i * 7);
      const e = new Date(d); e.setDate(e.getDate() + 6);
      out.push({ x: i * weekPx, wk: isoWeek(d), range: `${String(d.getDate()).padStart(2, "0")} ${MONTHS[d.getMonth()]}–${String(e.getDate()).padStart(2, "0")} ${MONTHS[e.getMonth()]}` });
    }
    return out;
  }, [dom, weekPx]);

  const months = useMemo(() => {
    const out: { x: number; w: number; label: string }[] = [];
    const d = new Date(dom.lo);
    while (d < dom.hi) {
      const s = new Date(d);
      const e = new Date(d.getFullYear(), d.getMonth() + 1, 1);
      const cut = e > dom.hi ? dom.hi : e;
      out.push({ x: ((+s - +dom.lo) / DAY) * pxDay, w: ((+cut - +s) / DAY) * pxDay, label: `${MONTHS[s.getMonth()]} ${String(s.getFullYear()).slice(2)}` });
      d.setMonth(d.getMonth() + 1);
    }
    return out;
  }, [dom, pxDay]);

  const groups = useMemo(() => {
    const key = (l: Lane) =>
      f.group === "plant" ? (l.plant || "no plant") : f.group === "buyer" ? (l.buyer || "—")
        : f.group === "dept" ? "BY-DEPT" : f.group === "style" ? styleOf(l.sku) : l.wip;
    const m = new Map<string, Lane[]>();
    lanes.forEach((l) => m.set(key(l), [...(m.get(key(l)) || []), l]));
    return m;
  }, [lanes, f.group]);

  const orderOf = (wip: string) => plan.orders.find((o) => o.wip === wip);
  const gridBg = `repeating-linear-gradient(to right, var(--border) 0 1px, transparent 1px ${weekPx}px)`;
  const depts = f.dept ? [f.dept] : plan.facets.departments;
  const byDept = f.group === "dept";
  const LANE_H = 40;
  const HEAD_H = 46;

  /* one lane's picture: window bar + gate diamond + actual dot, on the timeline */
  const drawGate = (l: Lane, b: Bar, i: number) => {
    const e2 = x(b.end);
    if (e2 === null) return null;
    const s1 = x(b.start);
    const col = statusColour(b.status);
    const act = x(b.actual);
    const tip = [
      `${b.milestone}${b.department ? ` · ${b.department}` : ""}`,
      `${b.marker_only ? "gate" : "window"} → ${pretty(b.end)}`,
      b.actual ? `actual ${pretty(b.actual)}${b.source ? ` (${b.source})` : ""}` : "not done",
      `${b.status}${b.late_days ? ` · ${b.late_days}d late` : ""}${b.slack_days != null ? ` · slack ${b.slack_days}d` : ""}`,
    ].join("\n");
    return (
      <div key={i} title={tip} onClick={() => onOpen(l)} style={{ position: "absolute", top: 0, bottom: 0, left: s1 ?? e2, width: s1 === null ? 0 : Math.max(1, e2 - s1), cursor: "pointer" }}>
        {/* the window the gate owns — light, because the DATE is the fact */}
        {s1 !== null && e2 - s1 > 2
          ? <div style={{ position: "absolute", left: 0, right: 0, top: 15, height: 7, borderRadius: 2,
              background: `${col}2e`, borderTop: `1px solid ${col}66`, borderBottom: `1px solid ${col}66` }} />
          : null}
        {/* the gate itself: filled when a document proves it, hollow when it is still to come */}
        <div style={{ position: "absolute", right: -4.5, top: 13, width: 10, height: 10, transform: "rotate(45deg)",
          background: b.status === "Done" ? GREEN : "var(--surface)",
          border: `1.6px solid ${b.status === "Done" ? GREEN : col}`,
          boxShadow: b.critical_now && b.status !== "Done" ? `0 0 0 2px ${AMBER}55` : undefined }} />
        {/* what actually happened, when it differs from the plan — and WHICH WAY it differed:
            a red dot after the diamond is late, a green dot before it finished early. Colour by direction,
            because 72 of the 72 proved gates here happened on a different day from the template's. */}
        {act !== null && Math.abs(act - e2) > 1.5 ? (() => {
          const wasLate = act > e2;
          const c = wasLate ? RED : GREEN;
          return (
            <>
              <div style={{ position: "absolute", left: Math.min(act, e2), width: Math.abs(act - e2), top: 17, height: 0, borderTop: `1px dashed ${c}99` }} />
              <div title={`actually ${pretty(b.actual)} — ${wasLate ? "later" : "earlier"} than the ${pretty(b.end)} gate`}
                style={{ position: "absolute", left: act - 3, top: 14, width: 6, height: 6, borderRadius: 6, background: c }} />
            </>
          );
        })() : null}
      </div>
    );
  };

  return (
    <Card
      title="Time & Action — every gate in the window it owns"
      sub={byDept
        ? "grouped by department: only that department's gates are drawn, per SKU — the workload view"
        : "week columns · ◆ = the date to hit (filled = proved by a document) · light bar = the window that gate owns · a red dot after a ◆ is where it actually happened"}
      actions={
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <div style={{ display: "inline-flex", border: "1px solid var(--border)", borderRadius: 7, overflow: "hidden" }}>
            {(["weeks", "days"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                style={{ ...btn, border: "none", borderRadius: 0, background: dense === m ? "var(--surface-sunken)" : "var(--surface)", color: dense === m ? "var(--text)" : "var(--text-muted)" }}>
                {m === "weeks" ? "Weeks" : "Days"}
              </button>
            ))}
          </div>
          <button style={btn} onClick={() => setDayPx((v) => Math.max(dense === "weeks" ? 3.5 : 1.1, +(v / 1.35).toFixed(2)))}>−</button>
          <button style={btn} onClick={() => setDayPx((v) => Math.min(dense === "weeks" ? 16 : 12, +(v * 1.35).toFixed(2)))}>+</button>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{Math.round(weekPx)} px / week</span>
        </div>
      }
    >
      <div style={{ overflowX: "auto", overflowY: "hidden", maxWidth: "100%" }}>
        <div style={{ display: "flex", width: "max-content", minWidth: "100%", position: "relative" }}>
          {/* ── left: the readable column ── */}
          <div style={{ width: 232, flex: "0 0 232px", position: "sticky", left: 0, zIndex: 4, background: "var(--surface)", borderRight: "1px solid var(--border-strong)" }}>
            <div style={{ height: HEAD_H, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "flex-end", padding: "0 8px 5px", fontSize: 10, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)" }}>
              {byDept ? "Department · SKU" : f.group === "order" ? "Buyer · order · SKU" : `${f.group} · SKU`}
            </div>
            {byDept
              ? depts.map((dept) => {
                  const rows = lanes.filter((l) => l.bars.some((b) => b.department === dept));
                  return (
                    <div key={dept}>
                      <div onClick={() => setShut((c) => ({ ...c, [dept]: !c[dept] }))}
                        style={{ height: 30, borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)", background: "var(--surface-sunken)", display: "flex", alignItems: "center", gap: 6, padding: "0 8px", fontSize: 11.5, fontWeight: 700, cursor: "pointer" }}>
                        <span style={{ color: "var(--text-muted)", width: 10 }}>{shut[dept] ? "▸" : "▾"}</span>
                        <span style={{ width: 16, height: 16, borderRadius: 3, background: "var(--surface)", border: "1px solid var(--border-strong)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 9.5, fontWeight: 800 }}>{DEPT_TAG[dept] || dept[0]}</span>
                        {dept}
                        <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--text-muted)" }}>{rows.length}</span>
                      </div>
                      {!shut[dept] && rows.map((l) => laneName(l, onOpen, true))}
                    </div>
                  );
                })
              : Array.from(groups.entries()).map(([gkey, gl]) => {
                  const o = orderOf(gkey);
                  const late = gl.reduce((a, l) => a + l.bars.filter((b) => b.status === "Late").length, 0);
                  return (
                    <div key={gkey}>
                      <div onClick={() => setShut((c) => ({ ...c, [gkey]: !c[gkey] }))}
                        style={{ height: 30, borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)", background: "var(--surface-sunken)", display: "flex", alignItems: "center", gap: 6, padding: "0 8px", cursor: "pointer" }}
                        title={o ? `${o.wip} · ${o.qty.toLocaleString()} pcs · ships ${o.ship_date} · ${o.plant || "no plant"}` : gkey}>
                        <span style={{ color: "var(--text-muted)", width: 10 }}>{shut[gkey] ? "▸" : "▾"}</span>
                        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 11.5, fontWeight: 700 }}>
                          {f.group === "order" ? (o?.buyer || gkey) : `${gkey} · ${gl.length} SKU`}
                        </span>
                        {late ? <span style={{ marginLeft: "auto" }}><Pill tone={RED}>{late} late</Pill></span> : null}
                      </div>
                      {!shut[gkey] && gl.map((l) => laneName(l, onOpen, false))}
                    </div>
                  );
                })}
          </div>

          {/* ── right: the timeline ── */}
          <div style={{ position: "relative", width: Math.max(width, 420), minWidth: Math.max(width, 420),
                        flex: "0 0 auto" }}>
            {/* month band */}
            <div style={{ height: 22, position: "relative", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
              {months.map((m) => (
                <div key={m.x} style={{ position: "absolute", left: m.x, width: m.w, top: 0, bottom: 0, borderLeft: "1px solid var(--border-strong)", fontSize: 10.5, fontWeight: 700, color: "var(--text-secondary)", padding: "4px 0 0 5px", overflow: "hidden", whiteSpace: "nowrap" }}>
                  {m.label}
                </div>
              ))}
            </div>
            {/* week band */}
            <div style={{ height: 24, position: "relative", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
              {weeks.map((w) => (
                <div key={w.x} style={{ position: "absolute", left: w.x, width: weekPx, top: 0, bottom: 0, borderLeft: "1px solid var(--border)", padding: "2px 0 0 3px", overflow: "hidden", whiteSpace: "nowrap" }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-secondary)", lineHeight: 1.1 }}>Wk {w.wk}</div>
                  {showRange ? <div style={{ fontSize: 8.5, color: "var(--text-muted)", lineHeight: 1.1 }}>{w.range}</div> : null}
                </div>
              ))}
              <span style={{ position: "absolute", left: todayX, top: 1, fontSize: 9, fontWeight: 700, color: RED, background: "var(--surface)", padding: "0 3px", borderRadius: 3, transform: "translateX(-50%)", zIndex: 5 }}>today</span>
            </div>

            {byDept
              ? depts.map((dept) => {
                  const rows = lanes.filter((l) => l.bars.some((b) => b.department === dept));
                  return (
                    <div key={dept}>
                      <div style={{ height: 30, background: "var(--surface-sunken)", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }} />
                      {!shut[dept] && rows.map((l) => (
                        <div key={l.wip + l.sku + dept} style={{ height: LANE_H, borderBottom: "1px solid var(--border)", position: "relative", backgroundImage: gridBg }}>
                          {l.bars.filter((b) => b.department === dept).map((b, i) => drawGate(l, b, i))}
                        </div>
                      ))}
                    </div>
                  );
                })
              : Array.from(groups.entries()).map(([gkey, gl]) => {
                  const o = orderOf(gkey);
                  const shipX = o ? x(o.ship_date) : null;
                  return (
                    <div key={gkey}>
                      {/* order row: the promised ship date, marked */}
                      <div style={{ height: 30, background: "var(--surface-sunken)", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)", position: "relative", backgroundImage: gridBg }}>
                        {shipX !== null && o ? (
                          <div title={`${o.buyer} ships ${o.ship_date} · ${o.plant || "no plant"} · ${o.qty.toLocaleString()} pcs`}
                            style={{ position: "absolute", left: shipX, top: 0, bottom: 0, borderLeft: `2px solid ${BLUE}`, zIndex: 2 }}>
                            <span style={{ position: "absolute", left: 3, top: 7, fontSize: 9.5, fontWeight: 700, color: BLUE, background: "var(--surface-sunken)", padding: "0 3px", borderRadius: 3, whiteSpace: "nowrap" }}>
                              ship {pretty(o.ship_date)}
                            </span>
                          </div>
                        ) : null}
                      </div>
                      {!shut[gkey] && gl.map((l) => (
                        <div key={l.wip + l.sku} style={{ height: LANE_H, borderBottom: "1px solid var(--border)", position: "relative", backgroundImage: gridBg }}>
                          {l.bars.map((b, i) => drawGate(l, b, i))}
                        </div>
                      ))}
                    </div>
                  );
                })}

            <div style={{ position: "absolute", left: todayX, top: HEAD_H, bottom: 0, borderLeft: `1.5px dashed ${RED}`, pointerEvents: "none", zIndex: 3 }} />
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginTop: 10, fontSize: 11, color: "var(--text-muted)" }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 10, height: 10, transform: "rotate(45deg)", background: GREEN, display: "inline-block" }} />◆ proved by a document
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 10, height: 10, transform: "rotate(45deg)", border: `1.6px solid ${RED}`, display: "inline-block" }} />◆ late, not done
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 10, height: 10, transform: "rotate(45deg)", border: `1.6px solid ${GREY}`, display: "inline-block" }} />◆ still to come
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 16, height: 7, background: `${GREY}2e`, borderTop: `1px solid ${GREY}66`, borderBottom: `1px solid ${GREY}66`, display: "inline-block" }} />the window the gate owns
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 6, height: 6, borderRadius: 6, background: RED, display: "inline-block" }} />where it actually happened — <span style={{ color: RED }}>red = later</span> / <span style={{ color: GREEN }}>green = earlier</span> than the gate
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 2, height: 12, background: BLUE, display: "inline-block" }} />promised ship date
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <i style={{ width: 2, height: 12, background: RED, display: "inline-block" }} />today
        </span>
      </div>
    </Card>
  );
}

/* the lane's name cell: SKU, its department tag, and the row read out loud on the right */
function laneName(l: Lane, onOpen: (l: Lane) => void, byDept: boolean) {
  const rag = ragOf(l.recovery);
  const days = l.recovery.days_left;
  return (
    <div key={l.wip + l.sku + (byDept ? "d" : "")} onClick={() => onOpen(l)}
      title={`${l.sku} · ${l.wip} · ${Math.round(l.qty).toLocaleString()} pcs · click for the catch-up plan`}
      style={{ height: 40, borderBottom: "1px solid var(--border)", padding: "3px 8px 3px 26px", cursor: "pointer", display: "flex", flexDirection: "column", justifyContent: "center", gap: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.sku}</span>
        <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text-muted)" }}>{Math.round(l.qty)}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--text-muted)", minWidth: 0 }}>
        <Pill tone={rag.tone}>{rag.label}</Pill>
        {l.next_milestone
          ? <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.next_milestone}{days != null ? ` · ${days}d` : ""}</span>
          : <span>{l.stage || "—"}</span>}
      </div>
    </div>
  );
}

/* ── calendar ───────────────────────────────────────────────────────────────── */
function Calendar({ plan, lanes, f }: { plan: Plan; lanes: Lane[]; f: Filter }) {
  const allowed = new Set(lanes.map((l) => l.wip + "|" + l.sku));
  const chips = plan.calendar.chips.filter((c) => (!f.dept || c.department === f.dept) && allowed.has(c.wip + "|" + c.sku));
  const months = plan.calendar.months;
  const [month, setMonth] = useState(months.includes(todayISO().slice(0, 7)) ? todayISO().slice(0, 7) : months[0] || todayISO().slice(0, 7));
  const [day, setDay] = useState<string | null>(null);
  useEffect(() => { if (!months.includes(month) && months[0]) { setMonth(months[0]); setDay(null); } }, [months, month]);
  // a day picked in another month must not linger in the detail panel
  useEffect(() => { if (day && !day.startsWith(month)) setDay(null); }, [month, day]);

  const inMonth = chips.filter((c) => c.date.slice(0, 7) === month);
  const byDay = new Map<string, Chip[]>();
  inMonth.forEach((c) => byDay.set(c.date, [...(byDay.get(c.date) || []), c]));
  const [y, mo] = month.split("-").map(Number);
  const first = new Date(y, mo - 1, 1);
  const pad = (first.getDay() + 6) % 7;
  const days = new Date(y, mo, 0).getDate();
  // ALWAYS six rows: a five-row month followed by a six-row month makes the whole page jump, which is what
  // "the calendar glitches" looks like when you click through months.
  const cells: (number | null)[] = [...Array.from({ length: pad }, () => null), ...Array.from({ length: days }, (_, i) => i + 1)];
  while (cells.length < 42) cells.push(null);
  const picked = day ? byDay.get(day) || [] : [];

  return (
    <Card title="Calendar — every drop-dead on its own day"
      sub={`${inMonth.length} gate(s) this month · ${inMonth.filter((c) => c.status === "Late").length} late · click a day for the list`}
      actions={<select style={selStyle} value={month} onChange={(e) => { setMonth(e.target.value); setDay(null); }}>
        {months.map((m) => { const [yy, mm] = m.split("-"); return <option key={m} value={m}>{MONTHS[Number(mm) - 1]} {yy}</option>; })}
      </select>}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(80px, 1fr))", gap: 1, background: "var(--border)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
          <div key={d} style={{ background: "var(--surface-sunken)", padding: "5px 7px", fontSize: 10, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)" }}>{d}</div>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <div key={`p${i}`} style={{ background: "var(--surface-sunken)", minHeight: 88 }} />;
          const key = `${month}-${String(d).padStart(2, "0")}`;
          const list = byDay.get(key) || [];
          const isToday = key === todayISO();
          const lateN = list.filter((c) => c.status === "Late").length;
          return (
            <div key={key} onClick={() => setDay(list.length ? key : null)}
              style={{ background: day === key ? "#eef7ff" : "var(--surface)", minHeight: 88, maxHeight: 132, overflow: "hidden", padding: 5, cursor: list.length ? "pointer" : "default", outline: isToday ? `2px solid ${BLUE}` : "none", outlineOffset: -2 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 3 }}>
                <span style={{ fontSize: 11, fontWeight: isToday ? 800 : 600, color: isToday ? BLUE : "var(--text-secondary)" }}>{d}</span>
                {list.length ? <span style={{ marginLeft: "auto", fontSize: 9.5, color: lateN ? RED : "var(--text-muted)" }}>{list.length}{lateN ? ` · ${lateN} late` : ""}</span> : null}
              </div>
              {list.slice(0, 3).map((c, j) => (
                <div key={j} title={`${c.milestone} · ${c.sku} · ${c.order || ""} · ${c.department || ""} · ${c.status}${c.late_days ? ` · ${c.late_days}d late` : ""}`}
                  style={{ fontSize: 9.5, lineHeight: 1.35, marginBottom: 2, padding: "0 3px", borderRadius: 3, background: `${statusColour(c.status)}1f`, borderLeft: `3px solid ${statusColour(c.status)}`, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis", color: "var(--text-secondary)" }}>
                  {c.milestone}
                </div>
              ))}
              {list.length > 3 ? <div style={{ fontSize: 9.5, color: "var(--text-muted)" }}>+{list.length - 3} more</div> : null}
            </div>
          );
        })}
      </div>
      {picked.length ? (
        <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ background: "var(--surface-sunken)", padding: "6px 10px", fontSize: 11.5, fontWeight: 700 }}>{pretty(day)} · {picked.length} gate(s)</div>
          <div style={{ maxHeight: 200, overflowY: "auto" }}>
            {picked.map((c, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", padding: "5px 10px", borderTop: "1px solid var(--border)", fontSize: 11.5 }}>
                <i style={{ width: 8, height: 8, borderRadius: 8, background: statusColour(c.status), flex: "0 0 8px" }} />
                <b style={{ minWidth: 140 }}>{c.milestone}</b>
                <span style={{ color: "var(--text-secondary)" }}>{c.sku}</span>
                <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>{c.order}</span>
                {c.late_days ? <Pill tone={RED}>{c.late_days}d late</Pill> : <Pill tone={GREEN}>{c.status || ""}</Pill>}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div style={{ marginTop: 8 }}><Legend /></div>
    </Card>
  );
}

/* ── late & recovery ───────────────────────────────────────────────────────── */
function LateTable({ lanes, onOpen }: { lanes: Lane[]; onOpen: (l: Lane) => void }) {
  const rows = useMemo(
    () => lanes.filter((l) => l.recovery.state !== "DONE" && l.recovery.state !== "SLACK")
      .sort((a, b) => b.recovery.days_late - a.recovery.days_late),
    [lanes]
  );
  if (!rows.length) return <Card><Empty title="Nothing is off-plan" hint="Every SKU is either on time with days to spare, or already finished." good /></Card>;
  return (
    <Card title={`Late & recovery — ${rows.length} SKU(s) need a decision`}
      sub="worst first. PAST = the ship date has gone · TIGHT = the date holds only if the remaining gates are compressed · click a row for the catch-up schedule">
      <div style={{ maxHeight: 520, overflowY: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>{["Order", "SKU", "Pcs", "Worst late gate", "Days late", "State", "What it takes"].map((h) => (
              <th key={h} style={{ textAlign: "left", fontSize: 10, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "var(--text-muted)", padding: "5px 8px", borderBottom: "1px solid var(--border)", position: "sticky", top: 0, background: "var(--surface)" }}>{h}</th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.map((l) => {
              const r = l.recovery;
              const worst = [...l.bars].filter((b) => b.status === "Late").sort((a, b) => (b.late_days || 0) - (a.late_days || 0))[0];
              return (
                <tr key={l.wip + l.sku} onClick={() => onOpen(l)} style={{ cursor: "pointer", borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "6px 8px", fontSize: 11.5 }}>{l.order}<div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{l.buyer}</div></td>
                  <td style={{ padding: "6px 8px", fontSize: 11.5 }}>{l.sku}<div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{l.plant?.replace(/ Plant$/, "")}</div></td>
                  <td style={{ padding: "6px 8px", fontSize: 11.5 }}>{Math.round(l.qty).toLocaleString()}</td>
                  <td style={{ padding: "6px 8px", fontSize: 11.5 }}>{worst?.milestone || "—"}<div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{worst?.department || ""}</div></td>
                  <td style={{ padding: "6px 8px", fontSize: 11.5, color: RED, fontWeight: 700 }}>{r.days_late}</td>
                  <td style={{ padding: "6px 8px" }}><Pill tone={stateColour(r.state)}>{r.state}</Pill></td>
                  <td style={{ padding: "6px 8px", fontSize: 11, color: "var(--text-secondary)", maxWidth: 420 }}>{r.headline}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ── the drawer: the catch-up schedule + discussion ────────────────────────── */
function LaneDrawer({ lane, onClose, onChanged, notify }: { lane: Lane; onClose: () => void; onChanged: () => void; notify: (m: string) => void }) {
  const r = lane.recovery;
  const [thread, setThread] = useState<ThreadMsg[] | null>(null);
  const [msg, setMsg] = useState("");
  const [ship, setShip] = useState(lane.ship_date || "");
  const [busy, setBusy] = useState(false);

  const loadThread = useCallback(async () => {
    const res = await callApi("get_dashboard", { bridge_action: "get_wip_thread", wip: lane.wip });
    const d = res.success ? (res.data as any) : null;
    setThread(d?.thread || []);
  }, [lane.wip]);
  useEffect(() => { loadThread(); }, [loadThread]);

  const act = async (fn: string, params: Record<string, any>) => {
    setBusy(true);
    try {
      const res = await callApi("get_dashboard", { bridge_action: fn, ...params });
      const d = res.success ? (res.data as any) : null;
      if (d?.ok) { notify(d.message || "done"); setMsg(""); await loadThread(); onChanged(); }
      else notify(d?.reason || d?.error || "the action was refused");
    } catch (e: any) { notify(e?.message || "the action failed"); }
    finally { setBusy(false); }
  };

  return (
    <Drawer onClose={onClose} title={`${lane.sku} — the catch-up plan`} wide
      sub={<>{lane.wip} · {lane.order} · {lane.buyer} · {Math.round(lane.qty).toLocaleString()} pcs · {lane.plant?.replace(/ Plant$/, "")} · ships {pretty(lane.ship_date)}</>}>
      <div style={{ padding: "2px 2px 0" }}>

        <div style={{ border: `1px solid ${stateColour(r.state)}55`, background: `${stateColour(r.state)}0f`, borderRadius: 9, padding: "10px 12px", marginBottom: 12 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
            <Pill tone={stateColour(r.state)}>{r.state}</Pill>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{stateLabel(r.state)}</span>
          </div>
          <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>{r.headline}</div>
          <div style={{ display: "flex", gap: 14, marginTop: 8, flexWrap: "wrap", fontSize: 11, color: "var(--text-muted)" }}>
            <span>gate time needed <b style={{ color: "var(--text)" }}>{r.required_days}d</b></span>
            <span>calendar left <b style={{ color: r.spare_days < 0 ? RED : GREEN }}>{r.days_left}d</b></span>
            <span>spare/deficit <b style={{ color: r.spare_days < 0 ? RED : GREEN }}>{r.spare_days > 0 ? "+" : ""}{r.spare_days}d</b></span>
            <span>earliest ship <b style={{ color: "var(--text)" }}>{pretty(r.projected_ship)}</b></span>
          </div>
        </div>

        {r.late_gates.length ? (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--text-muted)", marginBottom: 5 }}>What is late</div>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
              {r.late_gates.map((g) => <Pill key={g} tone={RED}>{g}</Pill>)}
            </div>
          </div>
        ) : null}

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--text-muted)", marginBottom: 5 }}>
            The next plan — {r.state === "TIGHT" ? "compressed to hold the date" : "from today at the template's own pace"}
          </div>
          <div style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1.4fr 0.9fr 0.9fr 0.7fr 0.7fr", background: "var(--surface-sunken)", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--text-muted)" }}>
              {["Gate", "Planned", "Target", "Window", "Slack"].map((h) => <div key={h} style={{ padding: "5px 7px" }}>{h}</div>)}
            </div>
            <div style={{ maxHeight: 220, overflowY: "auto" }}>
              {r.remaining.map((x) => (
                <div key={x.milestone} style={{ display: "grid", gridTemplateColumns: "1.4fr 0.9fr 0.9fr 0.7fr 0.7fr", borderTop: "1px solid var(--border)", fontSize: 11.5 }}>
                  <div style={{ padding: "5px 7px" }}>{x.milestone}<div style={{ fontSize: 10, color: "var(--text-muted)" }}>{x.department}</div></div>
                  <div style={{ padding: "5px 7px", color: "var(--text-muted)" }}>{pretty(x.planned)}</div>
                  <div style={{ padding: "5px 7px", fontWeight: 700 }}>{pretty(x.target)}</div>
                  <div style={{ padding: "5px 7px", color: "var(--text-muted)" }}>{x.window_days ?? "—"}d</div>
                  <div style={{ padding: "5px 7px", color: (x.slack_days ?? 0) < 0 ? RED : (x.slack_days ?? 0) === 0 ? AMBER : GREEN }}>
                    {x.slack_days == null ? "—" : `${x.slack_days}d`}
                  </div>
                </div>
              ))}
              {!r.remaining.length ? <div style={{ padding: "8px", fontSize: 11.5, color: "var(--text-muted)" }}>every gate is cleared</div> : null}
            </div>
          </div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--text-muted)", marginBottom: 5 }}>Re-baseline</div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <input type="date" className="input input--sm" value={ship} onChange={(e) => setShip(e.target.value)} style={{ ...selStyle, minWidth: 140 }} />
            <button style={btn} disabled={busy || !ship || ship === lane.ship_date}
              onClick={() => act("wip_adjust", { wip: lane.wip, ship_date: ship, note: `moved from ${lane.ship_date}` })}>
              Move ship date &amp; shift open gates
            </button>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>actuals never move — only gates that have not happened</span>
          </div>
        </div>

        <div>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--text-muted)", marginBottom: 5 }}>Discussion</div>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <input className="input input--sm" placeholder="what was agreed…" value={msg} onChange={(e) => setMsg(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && msg.trim()) act("wip_comment", { wip: lane.wip, text: msg }); }}
              style={{ ...selStyle, flex: 1, minWidth: 180 }} />
            <button style={btn} disabled={busy || !msg.trim()} onClick={() => act("wip_comment", { wip: lane.wip, text: msg })}>Add</button>
          </div>
          <div style={{ maxHeight: 170, overflowY: "auto" }}>
            {thread === null ? <Skel h={40} /> : thread.length === 0
              ? <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>no comments yet — the thread is stored on the ERP record, so the desk sees it too</div>
              : thread.map((t, i) => (
                  <div key={i} style={{ borderLeft: `2px solid var(--border)`, padding: "3px 0 3px 8px", marginBottom: 6 }}>
                    <div style={{ fontSize: 11.5 }} dangerouslySetInnerHTML={{ __html: t.text.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") }} />
                    <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{t.by} · {t.at}</div>
                  </div>
                ))}
          </div>
        </div>
      </div>
    </Drawer>
  );
}

/* ── the queue: discuss → plan → finalise ──────────────────────────────────── */
function Queue({ plan, onChanged, notify }: { plan: Plan; onChanged: () => void; notify: (m: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [thread, setThread] = useState<ThreadMsg[]>([]);
  const [msg, setMsg] = useState("");
  const [ship, setShip] = useState("");
  const [busy, setBusy] = useState(false);
  const writesOff = plan.write_mode === "off";

  const pick = async (q: QueueItem) => {
    setOpen(q.wip || q.order || null);
    setShip(q.ship_date || "");
    setThread([]);
    if (q.wip) {
      const res = await callApi("get_dashboard", { bridge_action: "get_wip_thread", wip: q.wip });
      const d = res.success ? (res.data as any) : null;
      setThread(d?.thread || []);
    }
  };

  const act = async (fn: string, params: Record<string, any>) => {
    setBusy(true);
    try {
      const res = await callApi("get_dashboard", { bridge_action: fn, ...params });
      const d = res.success ? (res.data as any) : null;
      if (d?.ok) { notify(d.message || "done"); setMsg(""); onChanged(); if (fn.startsWith("wip_finalise")) setOpen(null); }
      else notify(d?.reason || d?.error || "the action was refused");
    } catch (e: any) { notify(e?.message || "the action failed"); }
    finally { setBusy(false); }
  };

  if (!plan.queue.length) {
    return (
      <Card title="Planning queue">
        <Empty title="Nothing waiting for a decision" good
          hint="Every submitted Sales Order already has a plan. The writer only *proposes*: when an order arrives, its plan lands here as a Draft for you to discuss and finalise — it never goes live on its own." />
      </Card>
    );
  }

  return (
    <Card title={`Planning queue — ${plan.queue.length} order(s) not planned yet`}
      sub={plan.write_mode === "off"
        ? "writes are OFF — you can read and discuss, but Finalise/Adjust will be refused until ERP_WRITE_MODE is draft or higher"
        : `write mode: ${plan.write_mode} — every action leaves a comment on the ERP record`}>
      {plan.queue.map((q) => {
        const key = q.wip || q.order || "";
        const isOpen = open === key;
        return (
          <div key={key} style={{ border: "1px solid var(--border)", borderRadius: 9, marginBottom: 8, overflow: "hidden" }}>
            <div onClick={() => pick(q)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", cursor: "pointer", background: isOpen ? "var(--surface-hover)" : "var(--surface)", flexWrap: "wrap" }}>
              <b style={{ fontSize: 12.5 }}>{q.order}</b>
              <span style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>{q.buyer}</span>
              <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{Math.round(q.qty).toLocaleString()} pcs · ships {pretty(q.ship_date)}</span>
              <span style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                {q.plan_state === "unplanned" ? <Pill tone={GREY}>no plan at all</Pill> : <Pill tone={AMBER}>proposal · {pretty(q.proposed_on)}</Pill>}
                {q.plant ? <Pill tone={BLUE}>{q.plant.replace(/ Plant$/, "")}</Pill> : null}
              </span>
            </div>
            {isOpen ? (
              <div style={{ padding: "10px 11px", borderTop: "1px solid var(--border)" }}>
                {q.allocation_note ? <div style={{ fontSize: 11.5, color: "var(--text-secondary)", marginBottom: 8 }}><b>Why this plant:</b> {q.allocation_note}</div> : null}
                {q.capacity ? (
                  <div style={{ fontSize: 11.5, color: "var(--text-secondary)", marginBottom: 8 }}>
                    <b>Capacity check:</b> {q.capacity.month} · plant {q.capacity.plant_capacity.toLocaleString()} pcs · booked before this order{" "}
                    {Math.max(0, q.capacity.booked - q.qty).toLocaleString()} pcs → this order{" "}
                    {Math.round((100 * q.qty) / Math.max(1, q.capacity.plant_capacity))}% of the month
                  </div>
                ) : null}
                {q.plan_state === "unplanned" ? (
                  <div style={{ fontSize: 12, color: AMBER, marginBottom: 8 }}>
                    No plan exists yet — <code>build/planning_build/build_wip.py --sync</code> proposes one (the 30-minute
                    heartbeat does it), and the proposal appears here with its dates and plant.
                  </div>
                ) : (
                  <>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
                      <input type="date" value={ship} onChange={(e) => setShip(e.target.value)} style={{ ...selStyle, minWidth: 140 }} />
                      <button style={{ ...btn, background: `${GREEN}14`, color: GREEN, borderColor: `${GREEN}55` }} disabled={busy || writesOff}
                        onClick={() => act("wip_finalise", { wip: q.wip, note: msg })}>
                        Finalise plan
                      </button>
                      <button style={btn} disabled={busy || writesOff || !ship || ship === q.ship_date}
                        onClick={() => act("wip_adjust", { wip: q.wip, ship_date: ship, note: msg })}>
                        Adjust &amp; keep as proposal
                      </button>
                      <button style={{ ...btn, color: RED, borderColor: `${RED}55` }} disabled={busy || writesOff}
                        onClick={() => act("wip_reject", { wip: q.wip, reason: msg || "not planning this one" })}>
                        Reject
                      </button>
                    </div>
                    <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                      <input className="input input--sm" placeholder="say what was agreed, then finalise…" value={msg} onChange={(e) => setMsg(e.target.value)} style={{ ...selStyle, flex: 1 }} />
                      <button style={btn} disabled={busy || !msg.trim()} onClick={() => act("wip_comment", { wip: q.wip, text: msg })}>Comment</button>
                    </div>
                    <div style={{ maxHeight: 150, overflowY: "auto" }}>
                      {thread.length === 0 ? <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>no comments yet</div>
                        : thread.map((t, i) => (
                            <div key={i} style={{ borderLeft: "2px solid var(--border)", padding: "3px 0 3px 8px", marginBottom: 5 }}>
                              <div style={{ fontSize: 11.5 }} dangerouslySetInnerHTML={{ __html: t.text.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") }} />
                              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{t.by} · {t.at}</div>
                            </div>
                          ))}
                    </div>
                  </>
                )}
              </div>
            ) : null}
          </div>
        );
      })}
    </Card>
  );
}


/* ── WIP analytics — the charts that are not the Gantt ───────────────────────
 * Every number here comes from `get_wip_analytics` with its own `basis` line, shown under each card, because a
 * zero that means "nothing is there" must never look like a zero that means "nothing is wrong".
 */
interface AStages { rows: { stage: string; qty: number; lanes: number; late: number; age_avg: number | null;
  age_max: number | null; buckets: Record<string, number>; aged_by: Record<string, number> }[];
  total_qty: number; buckets: string[]; basis: string }
interface AOutput { series: { date: string; made: number; cumulative: number }[]; total_made: number; order_qty: number;
  made_pct: number | null; plan_finish_last_pcd?: string | null; ship_last?: string | null;
  future_dated_rows: number; basis: string }
interface AEff { rows: { order?: string | null; buyer?: string | null; qty: number; boms_with_routing: number;
  sam_hours_allowed: number; plan_days?: number | null; sam_garments_per_day?: number | null; na?: string | null }[];
  basis: string }
interface AQual { rows: { stage: string; inspections: number; inspected_qty: number; rejected_qty: number;
  reject_pct: number | null; na?: string | null }[]; inspected_qty: number; rejected_qty: number;
  reject_pct: number | null; basis: string }
interface AComp { rows: { order?: string | null; buyer?: string | null; wip?: string | null; qty: number; made: number;
  made_pct: number | null; shipped: number; shipped_pct: number | null; gates_proved_pct: number | null;
  projected_finish?: string | null; ship_date?: string | null; state?: string | null; at_risk: boolean;
  over_produced: boolean }[]; basis: string }
interface AShort { rows: { doc: string; requisition: string; order?: string | null; status?: string | null;
  required_by?: string | null; required_qty: number; items_short: number;
  items: { item: string; need: number; in_stock: number; gap: number }[]; blocking: boolean }[];
  blocking: number; horizon_days: number; basis: string }
interface ARec { rows: { order?: string | null; buyer?: string | null; order_qty: number; made: number; shipped: number;
  in_factory: number; not_yet_made: number; residual: number; ties: boolean }[];
  totals: Record<string, number>; ties_everywhere: boolean | null; basis: string }
interface Analytics {
  today: string; read_ms: number; stock_entries_scanned: number;
  stages: AStages; output: AOutput; efficiency: AEff; quality: AQual; completion: AComp;
  shortage: AShort; reconcile: ARec; working_days?: WorkingDays; issues?: Plan["issues"]; policy?: Policy;
  basis: string;
}

const th: React.CSSProperties = { textAlign: "left", fontSize: 10, fontWeight: 700, letterSpacing: 0.4,
  textTransform: "uppercase", color: "var(--text-muted)", padding: "5px 8px", borderBottom: "1px solid var(--border)" };
const td: React.CSSProperties = { fontSize: 11.5, padding: "5px 8px", borderBottom: "1px solid var(--border)" };
const note: React.CSSProperties = { fontSize: 10.5, color: "var(--text-muted)", lineHeight: 1.45, marginTop: 8 };

function pctCell(v: number | null | undefined, tone?: string) {
  if (v === null || v === undefined) return <span style={{ color: "var(--text-muted)" }}>n/a</span>;
  return <b style={{ color: tone || (v >= 99.99 ? GREEN : v >= 50 ? "var(--text)" : AMBER) }}>{v}%</b>;
}

function AnalyticsTab({ analytics, notify }: { analytics: Analytics | null; notify: (m: string) => void }) {
  if (!analytics) return <Card title="WIP analytics"><Skel h={160} /></Card>;
  const a = analytics;
  const st = a.stages, ou = a.output, ef = a.efficiency, qu = a.quality, co = a.completion, sh = a.shortage, rc = a.reconcile;
  const bucketTotals = st.buckets.map((b) => ({ b, q: st.rows.reduce((x, r) => x + (r.buckets[b] || 0), 0) }));

  return (
    <>
      <Card title="Where the garments are — qty by stage"
        sub={`${st.total_qty.toLocaleString()} pcs across ${st.rows.length} stage(s) · age from the gate that put them there`}>
        {st.rows.length === 0 ? <Empty title="Nothing in WIP" hint="No WIP line carries a stage." /> : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: `140px repeat(${st.buckets.length}, 1fr) 90px 70px`, gap: 1,
              background: "var(--border)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
              <div style={{ ...th, background: "var(--surface-sunken)" }}>Stage</div>
              {st.buckets.map((b) => <div key={b} style={{ ...th, background: "var(--surface-sunken)", textAlign: "right" }}>{b} d</div>)}
              <div style={{ ...th, background: "var(--surface-sunken)", textAlign: "right" }}>Qty</div>
              <div style={{ ...th, background: "var(--surface-sunken)", textAlign: "right" }}>Late</div>
              {st.rows.map((r) => (
                <div key={r.stage} style={{ display: "contents" }}>
                  <div style={{ ...td, background: "var(--surface)", fontWeight: 600 }}>{r.stage}
                    <div style={{ fontSize: 9.5, color: "var(--text-muted)" }}>{r.lanes} SKU · avg {r.age_avg ?? "—"}d</div></div>
                  {st.buckets.map((b) => (
                    <div key={b} style={{ ...td, background: "var(--surface)", textAlign: "right",
                      color: r.buckets[b] ? (b === "10+" ? RED : b === "6-10" ? AMBER : "var(--text)") : "var(--text-muted)" }}>
                      {r.buckets[b] ? Math.round(r.buckets[b]).toLocaleString() : "—"}
                    </div>
                  ))}
                  <div style={{ ...td, background: "var(--surface)", textAlign: "right", fontWeight: 700 }}>{Math.round(r.qty).toLocaleString()}</div>
                  <div style={{ ...td, background: "var(--surface)", textAlign: "right", color: r.late ? RED : "var(--text-muted)" }}>{r.late || "—"}</div>
                </div>
              ))}
            </div>
            <div style={{ ...note }}>{st.basis}</div>
          </>
        )}
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12, marginTop: 12 }}>
        <Card title="Ageing — pieces sitting too long"
          sub={`buckets by days in the current stage · ${bucketTotals.reduce((x, y) => x + y.q, 0).toLocaleString()} pcs dated`}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {bucketTotals.map(({ b, q }) => {
              const max = Math.max(...bucketTotals.map((x) => x.q), 1);
              return (
                <div key={b} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 46, fontSize: 11, color: "var(--text-muted)" }}>{b} d</span>
                  <div style={{ flex: 1, height: 14, background: "var(--surface-sunken)", borderRadius: 4, overflow: "hidden" }}>
                    <div style={{ width: `${(100 * q) / max}%`, height: "100%",
                      background: b === "10+" ? RED : b === "6-10" ? AMBER : b === "3-5" ? BLUE : GREEN }} />
                  </div>
                  <span style={{ width: 64, textAlign: "right", fontSize: 11.5, fontWeight: 600 }}>{Math.round(q).toLocaleString()}</span>
                </div>
              );
            })}
          </div>
          <div style={note}>same basis as the stage table — a piece with no gate date is not in a bucket, it is counted under "Not started"</div>
        </Card>

        <Card title="Made vs the order book" sub={`${ou.total_made.toLocaleString()} of ${ou.order_qty.toLocaleString()} pcs · ${ou.future_dated_rows} future-dated row(s)`}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <div style={{ fontSize: 26, fontWeight: 700 }}>{ou.made_pct ?? "n/a"}<span style={{ fontSize: 14 }}>%</span></div>
            <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>cumulative made<br />last PCD {pretty(ou.plan_finish_last_pcd)} · last ship {pretty(ou.ship_last)}</div>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 90, marginTop: 10 }}>
            {ou.series.map((x) => {
              const max = Math.max(...ou.series.map((y) => y.cumulative), 1);
              return <div key={x.date} title={`${x.date} · made ${x.made} · cumulative ${x.cumulative}`}
                style={{ flex: 1, minWidth: 3, height: `${(100 * x.cumulative) / max}%`, background: "var(--chart-1)", borderRadius: 2, opacity: 0.85 }} />;
            })}
          </div>
          <div style={note}>{ou.basis}</div>
        </Card>
      </div>

      <Card style={{ marginTop: 12 }} title="Order completion & at-risk"
        sub="made % · shipped % · gates proved % · the projected finish from the recovery engine">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>{["Order", "Buyer", "Qty", "Made", "Shipped", "Gates proved", "Projected finish", "Ship", "State"].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>
            {co.rows.map((r) => (
              <tr key={r.order || "—"} style={{ background: r.at_risk ? `${RED}08` : undefined }}>
                <td style={td}>{r.order}{r.over_produced ? <Pill tone={AMBER}>over-produced</Pill> : null}</td>
                <td style={td}>{r.buyer}</td>
                <td style={td}>{Math.round(r.qty).toLocaleString()}</td>
                <td style={td}>{pctCell(r.made_pct)}</td>
                <td style={td}>{pctCell(r.shipped_pct)}</td>
                <td style={td}>{pctCell(r.gates_proved_pct)}</td>
                <td style={td}>{pretty(r.projected_finish)}</td>
                <td style={td}>{pretty(r.ship_date)}</td>
                <td style={td}>{r.state ? <Pill tone={stateColour(r.state as State)}>{r.state}</Pill> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={note}>{co.basis}</div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 12, marginTop: 12 }}>
        <Card title="SAM allowed vs the days you have" sub="the only time basis that is not seeded">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>{["Order", "Qty", "BOMs w/ routing", "SAM hours", "Plan days", "Pcs/day"].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {ef.rows.map((r) => (
                <tr key={r.order || "—"}>
                  <td style={td}>{r.order}</td>
                  <td style={td}>{Math.round(r.qty).toLocaleString()}</td>
                  <td style={td}>{r.boms_with_routing || <span style={{ color: AMBER }}>none</span>}</td>
                  <td style={td}>{r.sam_hours_allowed ? r.sam_hours_allowed.toLocaleString() : "—"}</td>
                  <td style={td}>{r.plan_days ?? "—"}</td>
                  <td style={td}>{r.sam_garments_per_day ? r.sam_garments_per_day.toLocaleString() : <span style={{ color: "var(--text-muted)" }}>n/a</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={note}>{ef.basis}</div>
        </Card>

        <Card title="Rejects by inspection point" sub={qu.reject_pct === null ? "nothing inspected yet" : `${qu.reject_pct}% of ${qu.inspected_qty.toLocaleString()} inspected`}>
          {qu.rows.length === 0 ? <Empty title="No submitted inspections" /> : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr>{["Inspected at", "Inspections", "Inspected qty", "Rejected", "Rate"].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
              <tbody>
                {qu.rows.map((r) => (
                  <tr key={r.stage}>
                    <td style={td}>{r.stage}</td><td style={td}>{r.inspections}</td>
                    <td style={td}>{r.inspected_qty.toLocaleString()}</td><td style={td}>{r.rejected_qty.toLocaleString()}</td>
                    <td style={td}>{r.na ? <span style={{ color: "var(--text-muted)" }}>n/a</span> : pctCell(r.reject_pct, r.reject_pct ? RED : GREEN)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={note}>{qu.basis}</div>
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 12, marginTop: 12 }}>
        <Card title={`Fabric & trims that block the plan — ${sh.blocking} blocking`}
          sub={`required vs stock in the Bin · open requisitions due within ${sh.horizon_days} days`}>
          {sh.rows.length === 0 ? <Empty title="Nothing short" good hint="Every requisition's required quantity is covered by stock." /> : (
            <div style={{ maxHeight: 280, overflowY: "auto" }}>
              {sh.rows.map((r) => (
                <div key={r.doc + r.requisition} style={{ borderTop: "1px solid var(--border)", padding: "6px 0" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11.5 }}>
                    <Pill tone={r.blocking ? RED : AMBER}>{r.blocking ? "blocking" : "short"}</Pill>
                    <b>{r.requisition}</b><span style={{ color: "var(--text-muted)" }}>{r.order}</span>
                    <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>due {pretty(r.required_by)}</span>
                  </div>
                  <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 2 }}>
                    {r.items.map((i) => `${i.item}: need ${i.need} / have ${i.in_stock} (gap ${i.gap})`).join(" · ")}
                    {r.items_short > r.items.length ? ` · +${r.items_short - r.items.length} more` : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={note}>{sh.basis}</div>
        </Card>

        <Card title="Does the arithmetic tie?"
          sub={rc.ties_everywhere === null ? "no orders to check" : rc.ties_everywhere ? "every order ties" : "a residual is showing"}>
          <div style={{ display: "flex", gap: 10, marginBottom: 8 }}>
            <Pill tone={rc.ties_everywhere ? GREEN : RED}>{rc.ties_everywhere ? "RECONCILED" : "DOES NOT TIE"}</Pill>
            <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
              {rc.totals.order_qty.toLocaleString()} ordered = {rc.totals.in_factory.toLocaleString()} in factory + {rc.totals.shipped.toLocaleString()} shipped + {rc.totals.not_yet_made.toLocaleString()} not yet made
            </span>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>{["Order", "Ordered", "Made", "Shipped", "In factory", "Not yet made", "Residual"].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {rc.rows.map((r) => (
                <tr key={r.order || "—"}>
                  <td style={td}>{r.order}</td>
                  <td style={td}>{Math.round(r.order_qty).toLocaleString()}</td>
                  <td style={td}>{Math.round(r.made).toLocaleString()}</td>
                  <td style={td}>{Math.round(r.shipped).toLocaleString()}</td>
                  <td style={td}>{Math.round(r.in_factory).toLocaleString()}</td>
                  <td style={td}>{Math.round(r.not_yet_made).toLocaleString()}</td>
                  <td style={{ ...td, color: Math.abs(r.residual) > 0.5 ? RED : GREEN }}>{r.residual}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={note}>{rc.basis}</div>
        </Card>
      </div>

      <Card style={{ marginTop: 12 }} title="Data-quality findings the Gantt has to survive"
        sub={a.issues ? `${a.issues.total} finding(s): ${Object.entries(a.issues.counts).map(([k, v]) => `${v} ${k}`).join(" · ")}` : ""}>
        {!a.issues || !a.issues.rows.length ? <Empty title="Nothing to flag" good /> : (
          <div style={{ maxHeight: 220, overflowY: "auto" }}>
            {a.issues.rows.slice(0, 60).map((i, n) => (
              <div key={n} style={{ display: "flex", gap: 8, padding: "3px 0", borderTop: "1px solid var(--border)", fontSize: 11.5 }}>
                <Pill tone={i.kind === "dependency violated" ? RED : AMBER}>{i.kind}</Pill>
                <span style={{ color: "var(--text-muted)", minWidth: 140 }}>{i.order}{i.sku ? ` · ${i.sku}` : ""}</span>
                <span>{i.detail}</span>
              </div>
            ))}
          </div>
        )}
        <div style={note}>{a.issues?.basis}</div>
      </Card>

      <Card style={{ marginTop: 12 }} title="What is counted, and what is not" sub="the counting policy, so a number cannot be read two ways">
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11.5, lineHeight: 1.7 }}>
          {(a.policy?.bases || []).map((b, i) => <li key={i} dangerouslySetInnerHTML={{ __html: b.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") }} />)}
        </ul>
        {a.working_days ? (
          <div style={{ marginTop: 8, padding: "8px 10px", borderRadius: 8, border: `1px solid ${a.working_days.confirmed ? "var(--border)" : AMBER + "55"}`, background: a.working_days.confirmed ? "var(--surface)" : `${AMBER}0f`, fontSize: 11.5 }}>
            <b>{a.working_days.confirmed ? "Working days available" : "Working days: UNCONFIRMED"}</b> — {a.working_days.basis}
          </div>
        ) : null}
        <div style={{ ...note }}>read {new Date().toLocaleTimeString()} · {a.read_ms} ms · {a.stock_entries_scanned} manufacture entries scanned</div>
      </Card>
    </>
  );
}

/* ── the tab ────────────────────────────────────────────────────────────────── */
export function WipPlanView() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"track" | "plan" | "gantt" | "calendar" | "late" | "queue" | "analytics">("track");
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [openLane, setOpenLane] = useState<Lane | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [f, setF] = useState<Filter>({ q: "", buyer: "", plant: "", dept: "", status: "", late: false, plan: "", group: "order", issues: false });

  const notify = useCallback((m: string) => { setToast(m); window.setTimeout(() => setToast((t) => (t === m ? null : t)), 6000); }, []);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setErr(null);
    try {
      const res = await callApi("get_dashboard", { bridge_action: "get_wip_plan", refresh: true });
      const d = res.success ? (res.data as any) : null;
      if (d?.orders) setPlan(d as Plan);
      else setErr(d?.error || res.message || "The plan could not be read from the ERP.");
    } catch (e: any) { setErr(e?.message || "The plan could not be read."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // analytics is a heavier read (manufacturing + stock + quality), so it loads when its tab is first opened
  const analyticsTried = useRef(false);
  useEffect(() => {
    if (mode !== "analytics" || analyticsTried.current) return;
    analyticsTried.current = true;
    (async () => {
      try {
        const res = await callApi("get_dashboard", { bridge_action: "get_wip_analytics", refresh: true });
        const d = res.success ? (res.data as any) : null;
        if (d?.stages) setAnalytics(d as Analytics);
      } catch { /* the tab shows its skeleton */ }
    })();
  }, [mode]);

  const lanes = useMemo(() => {
    if (!plan) return [];
    const q = f.q.trim().toLowerCase();
    return plan.lanes.filter((l) => {
      if (f.buyer && l.buyer !== f.buyer) return false;
      if (f.plant && l.plant !== f.plant) return false;
      if (f.status && l.status !== f.status) return false;
      if (f.plan && l.plan_state !== f.plan) return false;
      if (f.late && l.recovery.state !== "PAST" && l.recovery.state !== "TIGHT") return false;
      if (f.issues) {
        const mine = (plan.issues?.rows || []).some((i) => (i.sku && i.sku === l.sku && i.order === l.order) || (!i.sku && i.order === l.order));
        if (!mine) return false;
      }
      if (f.dept && !l.bars.some((b) => b.department === f.dept)) return false;
      if (q && !(`${l.sku} ${l.order} ${l.buyer} ${l.wip}`.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [plan, f]);

  if (loading && !plan) return <Card title="WIP plan"><Skel h={22} w="40%" /><div style={{ height: 10 }} /><Skel h={200} /></Card>;
  if (!plan || !plan.orders?.length) {
    return <Card><Empty title="No WIP to draw yet" hint={err || "Cortex WIP holds no records. build/planning_build/build_wip.py proposes one per submitted Sales Order; the 30-minute heartbeat keeps it current."} /></Card>;
  }

  const s = plan.summary;
  return (
    <>
      {toast ? <div style={{ marginBottom: 10, padding: "7px 11px", borderRadius: 8, background: "#eef7ff", border: "1px solid #cfe4ff", fontSize: 12 }}>{toast}</div> : null}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 12 }}>
        <Tile label="Orders on the floor" value={String(s.orders)} hint={`${s.skus} SKUs · ${s.pcs.toLocaleString()} pcs · ${s.committed} committed`} />
        <Tile label="SKUs off-plan" value={String(s.late_skus)} tone={s.late_skus ? RED : GREEN}
          hint={`${s.past} past ship · ${s.tight} tight`} />
        <Tile label="Late gates" value={String(s.late)} tone={s.late ? RED : GREEN}
          hint={`${s.done} proved · ${s.passed ?? 0} passed with no document · ${s.pending} ahead`} />
        <Tile label="Due in 7 days" value={String(s.next_7_days)} tone={BLUE} hint="not done, not waived" />
        <Tile label="Planning queue" value={String(s.queue)} tone={s.queue ? AMBER : GREEN} hint={s.proposals ? `${s.proposals} proposal(s)` : "nothing waiting"} />
      </div>

      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
        <div style={{ display: "inline-flex", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {([["track", "Track"], ["plan", `Plan${s.alerts ? ` · ${s.alerts} late` : ""}`],
             ["gantt", "Gantt"], ["calendar", "Calendar"],
             ["late", `Late & recovery${s.late_skus ? ` (${s.late_skus})` : ""}`],
             ["queue", `Queue${s.queue ? ` (${s.queue})` : ""}`], ["analytics", "Analytics"]] as const).map(([m, label]) => (
            <button key={m} type="button" onClick={() => setMode(m)}
              style={{ padding: "6px 13px", fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
                background: mode === m ? "var(--surface-sunken)" : "var(--surface)",
                color: mode === m ? "var(--text)" : "var(--text-muted)" }}>{label}</button>
          ))}
        </div>
        <button style={btn} onClick={() => load(true)} disabled={loading}>{loading ? "Reading…" : "Refresh"}</button>
        {plan.issues?.total ? (
          <button style={{ ...btn, color: AMBER, borderColor: `${AMBER}55` }} onClick={() => { setF({ ...f, issues: true }); setMode("analytics"); }}
            title={plan.issues.basis}>
            {plan.issues.total} data-quality finding(s)
          </button>
        ) : null}
        {plan.working_days && !plan.working_days.confirmed ? (
          <span style={{ fontSize: 10.5, color: AMBER, border: `1px solid ${AMBER}55`, background: `${AMBER}0f`, padding: "3px 7px", borderRadius: 6 }}
            title={plan.working_days.basis}>working days unconfirmed — all ages are elapsed days</span>
        ) : null}
        <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto" }} title="if this timestamp is not the latest, hard-reload (Ctrl-Shift-R) — the page is cached">
          {BUILD} · read {plan.generated_at ? new Date(plan.generated_at).toLocaleTimeString() : ""} · writes {plan.write_mode}
        </span>
      </div>

      {mode !== "queue" && mode !== "analytics" && mode !== "plan" ? <FilterBar f={f} set={(p) => setF({ ...f, ...p })} plan={plan} count={lanes.length} /> : null}

      {mode === "track" ? <Track plan={plan} lanes={lanes} onOpenOrder={(o) => { setF({ ...f, q: o.sales_order || "" }); setMode("gantt"); }} /> : null}
      {mode === "plan" ? <PlanBoard orders={plan.orders as any} alerts={(plan.alerts || []) as any}
        alertBasis={plan.alert_basis} onChanged={() => load(true)} notify={notify} /> : null}
      {mode === "gantt" ? <Gantt plan={plan} lanes={lanes} f={f} onOpen={setOpenLane} /> : null}
      {mode === "calendar" ? <Calendar plan={plan} lanes={lanes} f={f} /> : null}
      {mode === "late" ? <LateTable lanes={lanes} onOpen={setOpenLane} /> : null}
      {mode === "queue" ? <Queue plan={plan} onChanged={() => load(true)} notify={notify} /> : null}
      {mode === "analytics" ? <AnalyticsTab analytics={analytics} notify={notify} /> : null}

      {openLane ? <LaneDrawer lane={openLane} onClose={() => setOpenLane(null)} onChanged={() => load(true)} notify={notify} /> : null}
    </>
  );
}
