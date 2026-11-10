import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, RefreshCw, ServerCrash } from "lucide-react";
import { callApi, callInbox, callBridge } from "./services/api";
import { Gate } from "./cx/Gate";
import { Boot, bootSteps } from "./cx/Boot";
import { Workspace, NEEDS_DASH } from "./app/Workspace";
import { ChatPanel } from "./components/ChatPanel";
import { RiskDrawer } from "./components/RiskDrawer";
import { PreviewModal, IntentModal, DoneModal } from "./components/Modals";
import type { InputSpec } from "./components/Modals";
import { OverviewView } from "./views/OverviewView";
import { TnaView } from "./views/TnaView";
import { WipPlanView } from "./views/WipPlanView";
import { OrdersView } from "./views/OrdersView";
import { RisksView } from "./views/RisksView";
import { ActionsView } from "./views/ActionsView";
import { OperationsView } from "./views/OperationsView";
import { ActivityView } from "./views/ActivityView";
import { FabricIntelView } from "./views/FabricIntelView";
import { ForecastView } from "./views/ForecastView";
import { MailView } from "./views/MailView";
import { InboxView } from "./views/InboxView";
import { IntakeView } from "./views/IntakeView";
import { EnquiriesView } from "./views/EnquiriesView";
import { Skel } from "./ui";
import type { Dashboard, FabricIntel, InboxSummary, Rec, Risk, View } from "./types";

/* One line per tab: what it is, in plain words. */
const INFO: Record<View, { text: React.ReactNode; yes?: boolean; no?: boolean }> = {
  wip: {
    text: <><b>The production plan as a drawing.</b> One lane per order and size SKU, with all 13 milestones in the window each one owns — red where the date has passed, green where an ERP document proves it happened. The calendar tab answers "what is due this week" without a table.</>,
  },
  tna: {
    text: <><b>Time &amp; Action planning.</b> Every in-scope order planned backwards from its ship date — 61 milestones, live production actuals from the ERP, exceptions and alerts in one board. New orders arrive here as notifications to approve before work starts.</>,
  },
  overview: {
    text: <><b>One screen for the whole operation.</b> Order book, production, sourcing and shipping position. Anything in red already needs a decision — open it to see the evidence.</>,
  },
  orders: {
    text: <><b>Every live customer order</b> with its client PO, style, quantity, value and promised delivery date. Filter or search to find one.</>,
  },
  risks: {
    text: <><b>Everything the system thinks could go wrong</b>, most serious first — derived live from the ERP. Open a row for the full evidence behind it.</>,
  },
  actions: {
    text: <><b>Suggested next steps</b> for the risks above. <b>Preview only</b> — nothing here writes to the ERP until you approve it.</>,
  },
  operations: {
    text: <><b>The same ERP records, drawn as charts</b> — orders, production, quality, shipments and sourcing in one place, so you can see the shape of the business.</>,
  },
  fabric: {
    text: <><b>Four sources compared, style by style</b> — what the bill of materials says, what the internal costing says, what we ordered and what we actually pay. Hover any column heading to see what it means.</>,
    yes: true, no: true,
  },
  forecast: {
    text: <><b>Forward-looking projections from the live records</b> — delivery risk, stock-out cover, margin, cash (per currency) and supplier performance. Transparent arithmetic, no black box.</>,
    yes: true, no: true,
  },
  activity: {
    text: <><b>Every decision taken in this dashboard</b>, newest first — who approved or changed what, and when.</>,
  },
  mail: {
    text: <><b>Emails waiting for your approval.</b> KOGO drafts grounded, plain-text messages from the live records — nothing is sent until you approve it here.</>,
  },
  intake: {
    text: <><b>Read the mail, start the process.</b> The Tower opens the company mailbox, reads the attached PO or enquiry, extracts every field with a confidence, and prepares the ERP drafts — the Client PO, the Sales Order, the project. <b>Nothing is created until you approve it</b>, and a document it cannot read (a scan) is flagged rather than guessed.</>,
  },
  enquiries: {
    text: <><b>Every buyer asking for a price</b>, and what we already know about the styles they name. A style we made before carries the cost sheet, the BOM, the tech pack and the price we last sold it at — so an old-style enquiry is answered from the record, not from scratch.</>,
    yes: true,
  },
  inbox: {
    text: <><b>Your incoming mail, read and understood.</b> New orders, revised POs, invoices and questions are sorted automatically, matched to the live order they belong to, and anything that changes an order is flagged for your decision. <b>Nothing is applied to the ERP until you approve it.</b></>,
    yes: true,
  },
};

function Main({ me }: { me: Record<string, any> }) {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  /* The opening screen: shown once, long enough to read the name, and never after the first read. */
  const [bootMin, setBootMin] = useState(false);
  const [bootGone, setBootGone] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [offline, setOffline] = useState(false);

  const [view, setViewState] = useState<View>(() => ((location.hash.match(/^#\/([a-z_0-9]+)$/) || [])[1] as View) || "overview");
  /* The new shell owns navigation through the URL hash; the older screens still call setView(...). */
  const setView = useCallback((v: View) => { if (location.hash !== `#/${v}`) location.hash = `#/${v}`; setViewState(v); }, []);
  useEffect(() => {
    const on = () => { const k = (location.hash.match(/^#\/([a-z_0-9]+)$/) || [])[1]; if (k) setViewState(k as View); };
    window.addEventListener("hashchange", on); window.addEventListener("popstate", on);
    return () => { window.removeEventListener("hashchange", on); window.removeEventListener("popstate", on); };
  }, []);
  const [riskOpen, setRiskOpen] = useState<Risk | null>(null);

  const [askOpen, setAskOpen] = useState(false);
  const [askSeed, setAskSeed] = useState<string | undefined>(undefined);

  const [toast, setToast] = useState<{ msg: string; sticky: boolean; link?: { url: string; label: string } } | null>(null);
  const toastTimer = useRef<number | null>(null);
  const [modal, setModal] = useState<React.ReactNode | null>(null);
  const [busyRec, setBusyRec] = useState<number | null>(null);

  /* ── Fabric & price intelligence (fetched lazily the first time the tab opens) ── */
  const [fabric, setFabric] = useState<FabricIntel | null>(null);
  const [fabricLoading, setFabricLoading] = useState(false);
  const fabricTried = useRef(false);

  /* ── Inbox badge (pending inbound items needing a decision) ── */
  const [inbox, setInbox] = useState<InboxSummary | null>(null);

  /* ── Intake badge (documents read and waiting for a decision) ── */
  const [intakeCount, setIntakeCount] = useState(0);
  const [intakeRunId, setIntakeRunId] = useState<number | undefined>(undefined);

  /* Toasts must be READABLE: short confirmations fade, anything important
     (long text, errors, "required", "manual") stays until dismissed.
     A toast may carry an optional ACTION LINK (e.g. "Open in ERP"). */
  const notify = useCallback((msg: string, opts?: { sticky?: boolean; link?: { url: string; label: string } }) => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    const sticky = opts?.sticky ??
      (msg.length > 110 || /(required|manual|failed|could not|error|create|approve)/i.test(msg));
    setToast({ msg, sticky: sticky || !!opts?.link, link: opts?.link });
    if (!sticky && !opts?.link) toastTimer.current = window.setTimeout(() => setToast(null), 7000);
  }, []);

  const refresh = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    try {
      const res = await callApi("get_dashboard", {});
      const looksLikeDashboard = !!res.data && typeof res.data === "object" && Array.isArray((res.data as any).risks);
      if (res.success && looksLikeDashboard) {
        setDash(res.data as Dashboard);
        setOffline(false);
      } else {
        setOffline(true);
      }
      try {
        const s = await callInbox("get_inbox_summary");
        if (s.success && s.data) setInbox(s.data as InboxSummary);
      } catch { /* badge is best-effort */ }
      try {
        const i = await callInbox("get_intake_summary");
        if (i.success && i.data) setIntakeCount(Number((i.data as any).understood || 0));
      } catch { /* badge is best-effort */ }
    } catch {
      setOffline(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  /* The big operations read (risks, forecast …) is only needed by the older analysis screens, so it runs the first
     time one of them opens — the workspace itself never waits for it (2026-11-07). */
  const dashAsked = useRef(false);
  const ensureLegacy = useCallback((key: string) => {
    if (NEEDS_DASH.has(key) && !dashAsked.current) { dashAsked.current = true; void refresh(); }
    if (key === "fabric") setViewState("fabric");
  }, [refresh]);

  useEffect(() => { const t = window.setTimeout(() => setBootMin(true), 700); return () => window.clearTimeout(t); }, []);
  const bootReady = bootMin;
  useEffect(() => {
    if (!bootReady) return;
    const t = window.setTimeout(() => setBootGone(true), 480);
    return () => window.clearTimeout(t);
  }, [bootReady]);

  const loadFabric = useCallback(async () => {
    setFabricLoading(true);
    try {
      const res = await callApi("get_fabric_intelligence", {});
      if (res.success && res.data) setFabric(res.data as FabricIntel);
    } catch {
      /* keep whatever we had — the view shows an explicit unavailable state */
    } finally {
      setFabricLoading(false);
    }
  }, []);

  useEffect(() => {
    if (view !== "fabric" || fabricTried.current) return;
    fabricTried.current = true;
    loadFabric();
  }, [view, loadFabric]);

  /* ── Esc closes the top-most layer ─────────────────────────────────────── */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (modal) setModal(null);
      else if (riskOpen) setRiskOpen(null);
      else if (askOpen) { setAskOpen(false); setAskSeed(undefined); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal, riskOpen, askOpen]);

  /* ── action workflow ───────────────────────────────────────────────────── */
  const demandRecs = useMemo(() => (Array.isArray(dash?.recommendations) ? (dash as Dashboard).recommendations : []), [dash]);

  /* Step 2 of the write flow — an explicit confirmation before anything is written.
     Any Data-Entry the action needs is fetched first and shown as a form. */
  const openConfirm = async (rec: Rec, erpDoctype?: string) => {
    const risk = (dash?.risks ?? []).find((r) => r.id === rec.risk_id);
    if (!risk) { notify("Risk context is unavailable — refresh and try again."); return; }
    let inputs: InputSpec | undefined;
    let dtype = erpDoctype;
    try {
      const res = await callApi("preview_action", { action_id: rec.id });
      inputs = res?.data?.inputs;
      dtype = dtype || res?.data?.record?.doctype;
    } catch { /* no form spec — fall back to plain confirm */ }
    setModal(
      <IntentModal
        rec={rec}
        risk={risk}
        actionLabel={rec.action}
        erpDoctype={dtype}
        inputs={inputs}
        onPreview={() => openPreview(rec)}
        onApprove={(values) => { setModal(null); void approveAndRun(rec, values); }}
        onClose={() => setModal(null)}
      />
    );
  };

  const openPreview = async (rec: Rec) => {
    const res = await callApi("preview_action", { action_id: rec.id });
    if (res.success && res.data) {
      const doctype = res.data?.record?.doctype as string | undefined;
      setModal(
        <PreviewModal
          d={res.data}
          rec={rec}
          onConfirm={() => openConfirm(rec, doctype)}
          onClose={() => setModal(null)}
          notify={notify}
          onQueued={() => { setModal(null); setView("mail"); }}
        />
      );
    } else {
      notify("Could not build the preview.");
    }
  };

  /* Every decision / write shows a per-row spinner while it runs. */
  const withBusy = async (id: number, fn: () => Promise<void>) => {
    setBusyRec(id);
    try { await fn(); } finally { setBusyRec(null); }
  };

  /* Turn the write result into an honest toast: success / already done / failed. */
  const writeNote = (res: any): string =>
    res?.data?.result?.note || res?.data?.write?.reason || res?.message || "";

  const runAction = (rec: Rec, inputs?: Record<string, any>) => withBusy(rec.id, async () => {
    const res = await callApi("run_action", { action_id: rec.id, inputs: inputs || {} });
    const d: any = res.data || {};
    const status = d?.result?.status;
    if (res.success && status === "success") {
      notify(`Executed: ${rec.action}`);
      setModal(null);
      openDone(d, rec);
    } else if (res.success && (status === "blocked" || status === "already_done")) {
      notify(`Nothing to do — ${writeNote(res) || "this is already done."}`);
    } else {
      notify(`Could not execute: ${writeNote(res) || "unknown error."}`);
    }
    await refresh(true);
  });

  const decide = (rec: Rec, decision: "approve" | "reject") => withBusy(rec.id, async () => {
    const res = await callApi("decide_action", { action_id: rec.id, decision });
    if (res.success) {
      notify(res.data?.note ||
             (decision === "approve" ? `Approved: ${rec.action}` : `Rejected: ${rec.action}`));
      if (decision === "reject") setRiskOpen(null);
      await refresh(true);
    } else {
      notify("Could not update this action.");
    }
  });

  /* Confirm the draft(s) this action created inside the ERP (docstatus 0 → 1). */
  const submitInErp = (rec: Rec) => withBusy(rec.id, async () => {
    const res = await callBridge("submit_in_erp", { action_id: rec.id });
    const d: any = res.data || {};
    if (res.success && d.ok) {
      const fixed = Array.isArray(d.repaired) && d.repaired.length
        ? ` Auto-fixed: ${d.repaired.join("; ")}.` : "";
      notify(`Submitted ${d.count} record(s) in the ERP.${fixed}`);
      await refresh(true);
    } else if (Array.isArray(d.errors) && d.errors.length) {
      notify(`Submit failed: ${d.errors[0]}`);
    } else {
      notify(d.skipped?.[0]?.reason || "Nothing to submit for this action.");
    }
  });

  /* Reverse an executed action: delete/cancel what it created and reopen the risk. */
  const rollback = (rec: Rec) => withBusy(rec.id, async () => {
    const res = await callBridge("rollback_action", { action_id: rec.id });
    const d: any = res.data || {};
    const rb = d.rollback || {};
    if (res.success && rb.status === "rolled_back") {
      notify(`Rolled back: ${(rb.docs || []).join(", ") || rec.action}`);
      await refresh(true);
    } else {
      notify(rb.reason || "Nothing to roll back for this action.");
    }
  });

  /* After a write, pivot the user straight into the ERP for final confirmation. */
  const openDone = (d: any, rec: Rec) => {
    if (!d?.erp_url) return;
    setModal(
      <DoneModal
        d={d}
        onClose={() => setModal(null)}
        onSubmit={() => { setModal(null); void submitInErp(rec); }}
        busy={busyRec === rec.id}
      />
    );
  };

  const execute = (rec: Rec) => withBusy(rec.id, async () => {
    const res = await callApi("execute_action", { action_id: rec.id });
    if (res.success && !res.data?.error) {
      notify(`Executed: ${rec.action}`);
      await refresh(true);
    } else {
      notify(res.data?.error || "Approve the action first.");
    }
  });

  const modify = async (rec: Rec) => {
    const next = window.prompt("Modify this action:", rec.action);
    if (next && next.trim() && next !== rec.action) {
      await callApi("modify_action", { action_id: rec.id, new_text: next.trim() });
      await refresh(true);
      notify("Action wording updated.");
    }
  };

  const approveAndRun = (rec: Rec, inputs?: Record<string, any>) => withBusy(rec.id, async () => {
    await callApi("decide_action", { action_id: rec.id, decision: "approve" });
    const res = await callApi("run_action", { action_id: rec.id, inputs: inputs || {} });
    const d: any = res.data || {};
    const status = d?.result?.status;
    if (res.success && status === "success") {
      notify(`Approved & executed: ${rec.action}`);
      setModal(null);
      openDone(d, rec);
    } else if (res.success && status === "needs_input") {
      notify(`Data entry required — ${writeNote(res) || "fill the form and retry."}`);
      await refresh(true);
      void openConfirm(rec);
    } else if (res.success && (status === "blocked" || status === "already_done")) {
      notify(`Nothing to do — ${writeNote(res) || "this is already done."}`);
    } else {
      notify(`Could not execute: ${writeNote(res) || "unknown error."}`);
    }
    await refresh(true);
  });

  /* ── the shell is always shown; only the older dashboard screens wait for their data ───────── */
  /* an error-shaped answer (e.g. {"error": "unknown bridge action"}) must never unmount the app */
  const risksList: Risk[] = Array.isArray(dash?.risks) ? (dash as Dashboard).risks : [];
  const openRisks = risksList.filter((r) => r.status === "open");
  const connDown = dash?.connection?.connected === false;
  const drawerRecs = riskOpen ? demandRecs.filter((r) => r.risk_id === riskOpen.id) : [];



  const renderLegacy = (key: string) => {
    if (key === "tna") return <TnaView />;
    if (loading) return <div style={{ display: "grid", gap: 12 }}><Skel h={26} w="30%" /><Skel h={92} /><Skel h={220} /></div>;
    if (offline || !dash) {
      return (
        <div className="cx-card" style={{ textAlign: "center", padding: 32 }}>
          <div style={{ display: "grid", placeItems: "center", width: 48, height: 48, borderRadius: 14, background: "var(--negative-light)", color: "var(--negative-ink)", margin: "0 auto 14px" }}><ServerCrash size={22} /></div>
          <h2 style={{ fontSize: 17, fontWeight: 700 }}>This screen can’t load right now</h2>
          <p style={{ color: "var(--cx-label-2)", fontSize: 14, margin: "6px 0 18px" }}>The operations data didn’t answer. Other areas still work.</p>
          <button className="cx-btn" onClick={() => { setLoading(true); refresh(); }}><RefreshCw size={15} /> Try again</button>
        </div>
      );
    }
    return (
      <>
        {connDown && (
          <div className="cx-note cx-note--warn"><AlertTriangle size={18} /><div>ERP connection issue: {dash.connection?.error || "unavailable"} — showing the last known data.
            <button className="cx-btn cx-btn--sm cx-btn--gray" style={{ marginLeft: 10 }} onClick={() => refresh(true)}>Retry</button></div></div>
        )}
        {key === "overview" && <OverviewView dash={dash} openRisks={openRisks} onOpenRisk={setRiskOpen} onGoRisks={() => setView("risks")} onGoActions={() => setView("actions")} />}
        {key === "wip" && <WipPlanView />}
        {key === "orders" && <OrdersView orders={Array.isArray(dash.buyer_orders) ? dash.buyer_orders : []} />}
        {key === "risks" && <RisksView risks={risksList} onOpenRisk={setRiskOpen} />}
        {key === "actions" && (
          <ActionsView recs={demandRecs} risks={risksList} onPreview={openPreview} onApprove={(r) => openConfirm(r)} onReject={(r) => decide(r, "reject")}
            onExecute={(r) => openConfirm(r)} onSubmit={submitInErp} onRollback={rollback} busyId={busyRec} onModify={modify} onOpenRisk={setRiskOpen} />
        )}
        {key === "operations" && <OperationsView dash={dash} />}
        {key === "forecast" && <ForecastView dash={dash} />}
        {key === "fabric" && <FabricIntelView data={fabric} loading={fabricLoading} onRefresh={loadFabric} />}
        {key === "activity" && <ActivityView audit={Array.isArray(dash.audit_log) ? dash.audit_log : []} />}
        {key === "intake" && <IntakeView notify={notify} initialRunId={intakeRunId} />}
        {key === "inbox" && <InboxView notify={notify} onOpenIntake={(runId) => { setIntakeRunId(runId); setView("intake"); }} />}
        {key === "mail" && <MailView notify={notify} />}
      </>
    );
  };

  return (
    <>
      {!bootGone && <Boot done={bootReady} steps={bootSteps(bootReady ? 3 : 1, false)} status={bootReady ? "Ready" : "Opening the workspace"} />}

      <Workspace
        me={me}
        renderLegacy={renderLegacy}
        onLegacy={ensureLegacy}
        connected={!offline && !connDown}
        onAsk={() => { setAskSeed(undefined); setAskOpen(true); }}
      />

      {riskOpen && dash && (
        <RiskDrawer
          risk={riskOpen}
          recs={drawerRecs}
          onClose={() => setRiskOpen(null)}
          onPreview={openPreview}
          onApprove={(r) => openConfirm(r)}
          onReject={(r) => decide(r, "reject")}
          onExecute={(r) => openConfirm(r)}
          onSubmit={submitInErp}
          busyId={busyRec}
          onModify={modify}
          onAsk={(q) => { setRiskOpen(null); setAskSeed(q); setAskOpen(true); }}
        />
      )}

      {askOpen && <ChatPanel onClose={() => { setAskOpen(false); setAskSeed(undefined); }} initialInput={askSeed} />}

      {modal}
      {toast && (
        <div className="cx-toast" role="status" aria-live="polite">
          <span>{toast.msg}</span>
          {toast.link?.url && <a style={{ color: "#8ec5ff", fontWeight: 600 }} href={toast.link.url} target="_blank" rel="noreferrer">{toast.link.label || "Open in ERP"} ↗</a>}
          <button style={{ background: "none", border: 0, color: "inherit", fontSize: 20, cursor: "pointer" }} onClick={() => setToast(null)} aria-label="Dismiss">×</button>
        </div>
      )}
    </>
  );
}

export default function App() {
  return <Gate>{(me) => <Main me={me} />}</Gate>;
}
