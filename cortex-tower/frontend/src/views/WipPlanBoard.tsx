/* ── Plan — the process as five phases, and the dates as something you can move ────────────────
 *
 * The client, 2026-11-03: *"the process in the wip is wrong"*, then the real one in five phases, then:
 * *"what if say i want to pre plan dates and u suggest me and then i click how much + and −, and gradually
 * as days goes if i miss deadline, u alert me and then we do changes there too"*.
 *
 * So this tab is the loop, not a picture:
 *
 *   SUGGEST   every gate gets the date the gate master implies (delivery − offset). Nothing is written.
 *   NUDGE     −7 −1 +1 +7 on any gate. **Absorb** moves that gate only (the rest has to hold); **Cascade**
 *             moves that gate and everything after it, and the delivery date with it.
 *   ALERT     the gates already past their date with nothing behind them are listed first, with what they cost.
 *   SAVE      one write, `wip_apply_plan`. A gate whose rows are `Done` is never moved by it.
 *
 * Nothing here is stored until Save. The ERP is written once, with the dates the planner is looking at.
 */
import { useMemo, useState } from "react";
import { callApi } from "../services/api";
import { Card, Empty } from "../ui";

const RED = "#e0433c", GREEN = "#1f9d55", BLUE = "#2490ef", AMBER = "#c77700", GREY = "#8fa3b8";
const PASSED = "#7d8ea3";

export interface PlanGate {
  milestone: string; sequence: number; phase: number; phase_name?: string | null;
  offset_days: number; duration_days: number; department?: string | null; critical?: boolean;
  evidence_doctype?: string | null; duration_source?: string | null; source_note?: string | null;
  suggested?: string | null; planned?: string | null; actual?: string | null; status?: string | null;
  late_days?: number; delta_days?: number | null; skus_done?: number; skus?: number;
}
export interface PlanOrder {
  wip: string; sales_order?: string | null; buyer?: string | null; plant?: string | null;
  ship_date?: string | null; status?: string | null; plan_state?: string | null; qty: number;
  plan?: PlanGate[]; missed?: any[]; projected_ship?: string | null; slip_days?: number;
  gates_total?: number; gates_done?: number; gates_missed?: number; gates_unset?: number;
}
interface Props {
  orders: PlanOrder[];
  alerts: any[];
  alertBasis?: string;
  onChanged: () => void;
  notify: (m: string) => void;
}

const DAY = 86_400_000;
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (s: string, n: number) => iso(new Date(Date.parse(s + "T00:00:00Z") + n * DAY));
const todayISO = () => iso(new Date());
const DAYS = (a?: string | null, b?: string | null) =>
  a && b ? Math.round((Date.parse(a + "T00:00:00Z") - Date.parse(b + "T00:00:00Z")) / DAY) : null;
const pretty = (s?: string | null) => {
  if (!s) return "—";
  const d = new Date(s + "T00:00:00Z");
  return isNaN(+d) ? "—" : `${String(d.getUTCDate()).padStart(2, "0")} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
};
const statusTone = (s?: string | null) =>
  s === "Done" ? GREEN : s === "Late" ? RED : s === "Passed" ? PASSED : s === "No plan" ? AMBER : GREY;

const sel: React.CSSProperties = { fontSize: 12, padding: "5px 7px", border: "1px solid var(--border)",
  borderRadius: 7, background: "var(--surface)", color: "var(--text)" };
const btn: React.CSSProperties = { fontSize: 12, fontWeight: 600, padding: "5px 10px", border: "1px solid var(--border)",
  borderRadius: 7, background: "var(--surface)", color: "var(--text-secondary)", cursor: "pointer" };
const tiny: React.CSSProperties = { fontSize: 10, fontWeight: 700, padding: "2px 6px", border: "1px solid var(--border)",
  borderRadius: 5, background: "var(--surface)", color: "var(--text-secondary)", cursor: "pointer", minWidth: 26 };

function Pill({ tone, children, title }: { tone: string; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 700,
      padding: "1px 7px", borderRadius: 20, color: tone, background: `${tone}18`, border: `1px solid ${tone}44`, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

export function PlanBoard({ orders, alerts, alertBasis, onChanged, notify }: Props) {
  const [wip, setWip] = useState<string>(orders[0]?.wip || "");
  const [mode, setMode] = useState<"absorb" | "cascade">("absorb");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [ship, setShip] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [openPhase, setOpenPhase] = useState<Record<number, boolean>>({ 1: true, 2: true, 3: true, 4: true, 5: true });

  const order = useMemo(() => orders.find((o) => o.wip === wip) || orders[0], [orders, wip]);
  const base = useMemo(() => {
    const m: Record<string, string> = {};
    (order?.plan || []).forEach((g) => { if (g.planned || g.suggested) m[g.milestone] = (g.planned || g.suggested)!; });
    return m;
  }, [order]);
  const dateOf = (g: PlanGate) => draft[g.milestone] ?? base[g.milestone] ?? "";
  const dirty = Object.keys(draft).some((k) => draft[k] !== base[k]) || (ship !== "" && ship !== (order?.ship_date || ""));

  const missed = order?.missed || [];
  const shipDate = ship || order?.ship_date || "";
  // a gate that is N days late pushes its successors by N days: the honest projection is delivery + the worst
  // single overdue gate — never a sum of all of them, and never "on time" because the rest had slack.
  const worstOpen = useMemo(() => {
    const t = todayISO();
    return (order?.plan || []).reduce((worst, g) => {
      const d = draft[g.milestone] ?? base[g.milestone];
      if (!d || g.status === "Done" || g.status === "Passed" || (g.offset_days ?? 0) < 0) return worst;
      return Math.max(worst, DAYS(t, d) || 0);
    }, 0);
  }, [order, draft, base]);
  const projected = shipDate ? addDays(shipDate, worstOpen) : null;

  const phases = useMemo(() => {
    const out: { phase: number; name: string; gates: PlanGate[] }[] = [];
    (order?.plan || []).forEach((g) => {
      let p = out.find((x) => x.phase === g.phase);
      if (!p) { p = { phase: g.phase, name: g.phase_name || `Phase ${g.phase}`, gates: [] }; out.push(p); }
      p.gates.push(g);
    });
    return out.sort((a, b) => a.phase - b.phase);
  }, [order]);

  /** one click on a gate. `days` +1 = later. */
  const nudge = (g: PlanGate, days: number) => {
    const cur = dateOf(g);
    if (!cur) return;
    if (g.status === "Done" || g.status === "Passed") { notify(`${g.milestone} is already recorded — the plan may not move what happened.`); return; }
    const next: Record<string, string> = { ...draft, [g.milestone]: addDays(cur, days) };
    if (mode === "cascade") {
      // everything that came after this gate moves with it — including the delivery date
      const at = Date.parse(cur + "T00:00:00Z");
      (order?.plan || []).forEach((o) => {
        if (o.milestone === g.milestone || o.status === "Done" || o.status === "Passed") return;
        const d = draft[o.milestone] ?? base[o.milestone];
        if (d && Date.parse(d + "T00:00:00Z") > at) next[o.milestone] = addDays(d, days);
      });
      const shipNow = ship || order?.ship_date || "";
      if (shipNow && Date.parse(shipNow + "T00:00:00Z") >= at) setShip(addDays(shipNow, days));
    }
    setDraft(next);
  };

  const suggest = () => {
    const m: Record<string, string> = {};
    (order?.plan || []).forEach((g) => { if (g.suggested) m[g.milestone] = g.suggested; });
    setDraft(m);
    setShip(order?.ship_date || "");
    notify("Dates set back to the gate master's suggestion — nothing is written until you save.");
  };

  const save = async () => {
    const changes = Object.keys(draft).filter((k) => draft[k] !== base[k]).map((k) => `${k}=${draft[k]}`).join(";");
    if (!changes) { notify("Nothing to save — no date has changed."); return; }
    setBusy(true);
    try {
      const res = await callApi("get_dashboard", { bridge_action: "wip_apply_plan", wip: order?.wip, changes,
        ship_date: ship && ship !== (order?.ship_date || "") ? ship : "" });
      const d = res.success ? (res.data as any) : null;
      if (d?.ok) { notify(d.message || "Plan saved."); setDraft({}); onChanged(); }
      else notify(d?.reason || d?.error || "The plan was not saved.");
    } catch (e: any) { notify(e?.message || "The plan was not saved."); }
    finally { setBusy(false); }
  };

  const finalise = async () => {
    setBusy(true);
    try {
      const res = await callApi("get_dashboard", { bridge_action: "wip_finalise", wip: order?.wip, note: "" });
      const d = res.success ? (res.data as any) : null;
      notify(d?.ok ? (d.message || "Finalised.") : (d?.reason || "Not finalised."));
      if (d?.ok) onChanged();
    } catch (e: any) { notify(e?.message || "Not finalised."); }
    finally { setBusy(false); }
  };

  if (!orders.length) return <Card><Empty title="No plan to work on" hint="A Cortex WIP is proposed per submitted Sales Order." /></Card>;

  return (
    <>
      {/* ── the alerts, first: a deadline already gone is the reason this tab is open ── */}
      <Card title={`Missed gates — ${alerts.length}`}
        sub={alerts.length ? "a gate whose date has passed with no document and no goods behind it" : "nothing has slipped past its date"}>
        {!alerts.length ? <Empty title="Nothing missed" good hint="Every gate up to the delivery date is either proved or still ahead." /> : (
          <div style={{ maxHeight: 210, overflowY: "auto" }}>
            {alerts.slice(0, 40).map((a, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0",
                borderTop: i ? "1px solid var(--border)" : "none", fontSize: 11.5 }}>
                <Pill tone={RED}>{a.days_overdue}d late</Pill>
                <b style={{ minWidth: 150 }}>{a.milestone}</b>
                <span style={{ color: "var(--text-muted)", minWidth: 66 }}>P{a.phase}</span>
                <span style={{ color: "var(--text-muted)", minWidth: 140 }}>{a.order}</span>
                <span style={{ color: "var(--text-muted)" }}>was due {pretty(a.due)}</span>
                <button style={{ ...tiny, marginLeft: "auto" }} onClick={() => setWip(a.wip)}>open</button>
              </div>
            ))}
          </div>
        )}
        <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 6 }}>{alertBasis}</div>
      </Card>

      <Card style={{ marginTop: 12 }} title="Plan — the five phases, and every date in them"
        sub="suggest → nudge → save. Nothing reaches the ERP until you press Save, and a gate already recorded is never moved."
        actions={
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <select style={{ ...sel, minWidth: 250 }} value={wip} onChange={(e) => { setWip(e.target.value); setDraft({}); setShip(""); }}>
              {orders.map((o) => (
                <option key={o.wip} value={o.wip}>{o.sales_order} · {o.buyer} · {o.qty?.toLocaleString()} pcs</option>
              ))}
            </select>
            <div style={{ display: "inline-flex", border: "1px solid var(--border)", borderRadius: 7, overflow: "hidden" }}>
              {(["absorb", "cascade"] as const).map((m) => (
                <button key={m} onClick={() => setMode(m)} title={m === "absorb"
                  ? "move this gate only — the rest of the plan has to hold"
                  : "move this gate and everything after it, and the delivery date with it"}
                  style={{ ...btn, border: "none", borderRadius: 0,
                    background: mode === m ? "var(--surface-sunken)" : "var(--surface)",
                    color: mode === m ? "var(--text)" : "var(--text-muted)" }}>
                  {m === "absorb" ? "Absorb" : "Cascade"}
                </button>
              ))}
            </div>
            <button style={btn} onClick={suggest}>Suggest</button>
          </div>
        }>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center", marginBottom: 10, fontSize: 11.5 }}>
          <span><b>{order?.plan?.length || 0}</b> gates</span>
          <span style={{ color: GREEN }}><b>{order?.gates_done || 0}</b> proved</span>
          <span style={{ color: missed.length ? RED : "var(--text-muted)" }}><b>{missed.length}</b> missed</span>
          <span style={{ color: AMBER }}><b>{(order?.plan || []).filter((g) => g.status === "No plan").length}</b> not yet on the record</span>
          <span>delivery <input type="date" style={sel} value={shipDate} onChange={(e) => setShip(e.target.value)} /></span>
          {projected && worstOpen > 0 ? (
            <Pill tone={RED} title="the worst overdue gate pushes everything after it by the same number of days">
              if nothing moves: {pretty(projected)} ({worstOpen}d slip)
            </Pill>
          ) : <Pill tone={GREEN}>nothing overdue</Pill>}
          <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            {order?.plan_state === "proposal" ? <button style={btn} onClick={finalise} disabled={busy}>Finalise</button> : null}
            <button style={{ ...btn, fontWeight: 700, color: dirty ? "var(--text)" : "var(--text-muted)",
              borderColor: dirty ? BLUE : "var(--border)" }} onClick={save} disabled={!dirty || busy}>
              {busy ? "Saving…" : dirty ? "Save plan" : "Saved"}
            </button>
          </span>
        </div>

        {phases.map((p) => {
          const gates = p.gates;
          const dates = gates.map((g) => dateOf(g)).filter(Boolean).sort();
          const span = dates.length ? (DAYS(dates[dates.length - 1], dates[0]) || 0) : 0;
          const missedN = gates.filter((g) => {
            const d = dateOf(g); return d && d < todayISO() && g.status !== "Done" && g.status !== "Passed" && (g.offset_days ?? 0) >= 0;
          }).length;
          const isOpen = openPhase[p.phase] !== false;
          return (
            <div key={p.phase} style={{ border: "1px solid var(--border)", borderRadius: 9, marginBottom: 8, overflow: "hidden" }}>
              <div onClick={() => setOpenPhase((c) => ({ ...c, [p.phase]: !isOpen }))}
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", cursor: "pointer",
                  background: "var(--surface-sunken)", borderBottom: isOpen ? "1px solid var(--border)" : "none" }}>
                <span style={{ color: "var(--text-muted)", width: 10 }}>{isOpen ? "▾" : "▸"}</span>
                <span style={{ width: 22, height: 22, borderRadius: 5, background: "var(--surface)",
                  border: "1px solid var(--border-strong)", display: "inline-flex", alignItems: "center",
                  justifyContent: "center", fontSize: 11, fontWeight: 800 }}>P{p.phase}</span>
                <b style={{ fontSize: 12 }}>{p.name}</b>
                <span style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{gates.length} gates · {span} days</span>
                {missedN ? <span style={{ marginLeft: "auto" }}><Pill tone={RED}>{missedN} missed</Pill></span> : null}
              </div>
              {isOpen ? (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <tbody>
                    {gates.map((g) => {
                      const d = dateOf(g);
                      const tone = statusTone(g.status);
                      const vs = DAYS(d, g.suggested);
                      const late = d && d < todayISO() && g.status !== "Done" && g.status !== "Passed" && (g.offset_days ?? 0) >= 0;
                      return (
                        <tr key={g.milestone} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={{ padding: "5px 8px", fontSize: 11.5, fontWeight: 600, width: "30%" }}>
                            {g.milestone}
                            {g.critical ? <span title="critical gate" style={{ color: AMBER, marginLeft: 4 }}>●</span> : null}
                          </td>
                          <td style={{ padding: "5px 8px", fontSize: 10.5, color: "var(--text-muted)", width: "14%" }}>{g.department || "—"}</td>
                          <td style={{ padding: "5px 8px", fontSize: 10.5, color: "var(--text-muted)", width: "15%" }}
                            title={g.source_note || ""}>{g.evidence_doctype || "manual"}</td>
                          <td style={{ padding: "5px 8px", width: 132 }}>
                            <input type="date" style={{ ...sel, padding: "3px 5px", fontSize: 11.5, width: 122 }}
                              value={d || ""} disabled={g.status === "Done" || g.status === "Passed"}
                              onChange={(e) => setDraft({ ...draft, [g.milestone]: e.target.value })} />
                          </td>
                          <td style={{ padding: "5px 4px", whiteSpace: "nowrap" }}>
                            {[["−7", -7], ["−1", -1], ["+1", 1], ["+7", 7]].map(([lbl, n]) => (
                              <button key={lbl as string} style={{ ...tiny, marginRight: 3 }}
                                disabled={g.status === "Done" || g.status === "Passed"}
                                onClick={() => nudge(g, n as number)}>{lbl}</button>
                            ))}
                          </td>
                          <td style={{ padding: "5px 8px", width: 90 }}>
                            <Pill tone={late ? RED : tone}>{late ? `${DAYS(todayISO(), d)}d late` : (g.status || "—")}</Pill>
                          </td>
                          <td style={{ padding: "5px 8px", fontSize: 10.5, color: "var(--text-muted)", width: "16%" }}>
                            {g.duration_source === "measured" ? <span title={g.source_note || ""} style={{ color: GREEN }}>measured</span>
                              : g.duration_source === "pinned" ? "anchor"
                              : <span title={g.source_note || ""} style={{ color: AMBER }}>default</span>}
                            {vs !== null && vs !== 0 ? <span style={{ marginLeft: 6, color: vs > 0 ? RED : GREEN }}>{vs > 0 ? `+${vs}` : vs}d vs suggest</span> : null}
                            {g.actual ? <span style={{ marginLeft: 6 }}>· actual {pretty(g.actual)}</span> : null}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : null}
            </div>
          );
        })}
        <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 6 }}>
          <b>{mode === "absorb" ? "Absorb" : "Cascade"}</b> — {mode === "absorb"
            ? "a nudge moves that gate only; the ship date holds until the slack is gone, then it warns."
            : "a nudge moves that gate, everything after it, and the delivery date."} · a gate marked
          <span style={{ color: GREEN }}> measured</span> carries the client's own number; <span style={{ color: AMBER }}>default</span> has
          no number in their file yet and a planner sets it once.
        </div>
      </Card>
    </>
  );
}
