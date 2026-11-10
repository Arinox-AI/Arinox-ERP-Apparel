import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import TopBar, { type View } from "./components/TopBar";
import OrderRail from "./components/OrderRail";
import NeedsAttentionRail from "./components/NeedsAttentionRail";
import OfflineBanner from "./components/OfflineBanner";
import DataQualityBanner from "./components/DataQualityBanner";
import MilestoneDetailDrawer from "./components/MilestoneDetailDrawer";
import ConfirmPreviewModal from "./components/ConfirmPreviewModal";
import ToastStack, { type ToastItem } from "./components/Toast";
import EmptyState from "./components/EmptyState";
import IntakePanel from "./components/IntakePanel";
import type { UpdateFormValue } from "./components/UpdateMilestoneForm";

import PlanView from "./pages/Plan";
import BoardView from "./pages/Board";
import CalendarPage from "./pages/CalendarPage";
import Program from "./pages/Program";
import Template from "./pages/Template";
import Activity from "./pages/Activity";

import { checkApiHealth } from "./services/api";
import {
  getAuditLog, getHolidays, getTnaAlerts, getTnaCalendar, getTnaIntake, getTnaOrders,
  getTnaProgram, getTnaTemplate, approveTnaOrder, rejectTnaOrder, snoozeTnaOrder,
  setTowerLink, rollbackAction, runAction, unwrap, updateMilestone, pushMilestoneToErp,
} from "./services/tna";
import { USER_ID } from "./config";
import { todayISO } from "./lib/format";
import type {
  ActionRecord, AuditEntry, BridgeStatus, HolidayCalendar, IntakeNotification, IntakeSummary,
  Rag, TnaCalendar, TnaMilestone, TnaOrder, TnaTemplate, UpdateResult,
} from "./types";
import type { ApiStatus } from "./components/ApiStatusBadge";

/** Turn a raw middleware error into a readable, actionable message. */
function friendlyError(msg: string): { title: string; detail: string } {
  if (/not found\.\s*Available:/i.test(msg)) {
    return {
      title: "Backend not published yet",
      detail: `${msg} — the KOGO middleware exposes a project's callable functions from its last publish. ` +
        `This app starts working the moment this project is (re)published with backend/functions.py.`,
    };
  }
  if (/not found/i.test(msg) && /project/i.test(msg)) {
    return { title: "Project not found", detail: msg };
  }
  return { title: "Could not load the plan", detail: msg };
}

const ACTOR = USER_ID ? `user_${USER_ID.slice(0, 8)}` : "planner";

export default function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [view, setView] = useState<View>("plan");
  const [leftRail, setLeftRail] = useState(true);
  const [rightRail, setRightRail] = useState(true);

  const [orders, setOrders] = useState<TnaOrder[]>([]);
  // No order is assumed. The first Sales Order in the ERP fills this in (see loadStatic).
  const [orderId, setOrderId] = useState("");
  const [ordersLoaded, setOrdersLoaded] = useState(false);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const [calendarId, setCalendarId] = useState("VN_FACTORY");
  const [asOf, setAsOf] = useState(todayISO());
  // "today" is followed live: unless the user pins a date, as_of rolls forward by
  // itself (checked every minute and on focus/visibility), so the calendar always
  // contains the CURRENT month with no rebuild or re-prompt.
  const [asOfPinned, setAsOfPinned] = useState(false);
  const setAsOfManual = useCallback((v: string) => { setAsOfPinned(true); setAsOf(v || todayISO()); }, []);
  const resetAsOfToday = useCallback(() => { setAsOfPinned(false); setAsOf(todayISO()); }, []);
  const [ragByOrder, setRagByOrder] = useState<Record<string, Rag>>({});

  const [holidayCalendars, setHolidayCalendars] = useState<Record<string, HolidayCalendar>>({});
  const [template, setTemplate] = useState<TnaTemplate | null>(null);

  const [payload, setPayload] = useState<TnaCalendar | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [audit, setAudit] = useState<{ logs: AuditEntry[]; actions: ActionRecord[] }>({ logs: [], actions: [] });

  // ── intake / notifications ───────────────────────────────────────────────
  const [notifications, setNotifications] = useState<IntakeNotification[]>([]);
  const [intakeSummary, setIntakeSummary] = useState<IntakeSummary | null>(null);
  const [bridge, setBridge] = useState<BridgeStatus | null>(null);
  const [inboxOpen, setInboxOpen] = useState(false);
  const [intakeBusyId, setIntakeBusyId] = useState<string | null>(null);
  const [intakeError, setIntakeError] = useState<string | null>(null);
  const [savingTowerUrl, setSavingTowerUrl] = useState(false);

  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [preview, setPreview] = useState<UpdateResult | null>(null);
  const [previewOrigin, setPreviewOrigin] = useState<UpdateFormValue | null>(null);
  const [writeBusy, setWriteBusy] = useState(false);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const [digestBusy, setDigestBusy] = useState(false);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const payloadRef = useRef<TnaCalendar | null>(null);
  payloadRef.current = payload;

  // ── toasts ──────────────────────────────────────────────────────────────
  const dismissToast = useCallback((id: string) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const addToast = useCallback((t: Omit<ToastItem, "id">) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { ...t, id }]);
    if (!t.actionLabel) setTimeout(() => dismissToast(id), 5000);
  }, [dismissToast]);

  // ── health check (30s poll) ─────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    const check = async () => {
      const ok = await checkApiHealth();
      if (alive) setApiStatus(ok ? "connected" : "offline");
    };
    check();
    const iv = setInterval(check, 30000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  // ── static loads: orders, holidays, template ─────────────────────────────
  const loadStatic = useCallback(async () => {
    const [o, h, t] = await Promise.all([
      getTnaOrders({}),
      getHolidays({ calendar: "" }),
      getTnaTemplate({}),
    ]);
    const ordersRes = unwrap<{ orders: TnaOrder[]; warnings?: string[]; error?: string }>(o);
    setOrdersLoaded(true);
    const list = ordersRes.data?.orders || [];
    if (list.length) {
      setOrdersError(null);
      setOrders(list);
      setOrderId((prev) => (list.some((x) => x.order_id === prev) ? prev : list[0].order_id));
    } else {
      setOrders([]);
      setOrderId("");
      setOrdersError(ordersRes.error || ordersRes.data?.error || null);
    }
    const hRes = unwrap<{ calendars: Record<string, HolidayCalendar> }>(h);
    if (hRes.data?.calendars) setHolidayCalendars(hRes.data.calendars);
    const tRes = unwrap<TnaTemplate>(t);
    if (tRes.data) setTemplate(tRes.data);
  }, []);

  // ── rag per order (for the left rail) ────────────────────────────────────
  const loadRag = useCallback(async () => {
    try {
      const res = await getTnaProgram({ detail: false });
      const u = unwrap<{ orders: { order_id: string; rag: Rag }[] }>(res);
      if (u.data?.orders) {
        const map: Record<string, Rag> = {};
        u.data.orders.forEach((o) => { map[o.order_id] = o.rag; });
        setRagByOrder(map);
      }
    } catch { /* rail dot is cosmetic */ }
  }, []);

  // ── intake queue ─────────────────────────────────────────────────────────
  const loadIntake = useCallback(async (sync = true) => {
    try {
      const res = await getTnaIntake({ sync });
      const u = unwrap<{ notifications: IntakeNotification[]; summary: IntakeSummary; bridge: BridgeStatus }>(res);
      if (u.data) {
        setNotifications(u.data.notifications || []);
        setIntakeSummary(u.data.summary || null);
        setBridge(u.data.bridge || null);
        setIntakeError(null);
      } else {
        setIntakeError(u.error || "Could not load the intake queue.");
      }
    } catch (e: any) {
      setIntakeError(e?.message || "Could not load the intake queue.");
    }
  }, []);

  // ── audit log ───────────────────────────────────────────────────────────
  const loadAudit = useCallback(async (oid: string) => {
    try {
      const res = await getAuditLog({ order_id: oid, limit: 200 });
      const u = unwrap<{ logs: AuditEntry[]; actions: ActionRecord[] }>(res);
      if (u.data) setAudit({ logs: u.data.logs || [], actions: u.data.actions || [] });
    } catch { /* keep last */ }
  }, []);

  // ── the flagship calendar read ───────────────────────────────────────────
  const loadCalendar = useCallback(async () => {
    if (!orderId) { setPayload(null); setError(null); setLoading(false); return; }
    setLoading(true);
    try {
      const res = await getTnaCalendar({ order_id: orderId, calendar: calendarId, as_of: asOf });
      const u = unwrap<TnaCalendar>(res);
      if (u.error || !u.data) setError(u.error || "No data returned");
      else { setError(null); setPayload(u.data); }
    } catch (e: any) {
      setError(e?.message || "Request failed");
    } finally {
      setLoading(false);
    }
  }, [orderId, calendarId, asOf]);

  useEffect(() => { loadStatic(); loadIntake(true); loadRag(); }, [loadStatic, loadIntake, loadRag]);
  useEffect(() => { loadCalendar(); }, [loadCalendar]);
  useEffect(() => { loadAudit(orderId); }, [orderId, loadAudit]);

  // Keep the as-of date live so the calendar "follows today" by itself.
  useEffect(() => {
    const tick = () => {
      if (asOfPinned) return;
      setAsOf((prev) => { const t = todayISO(); return prev === t ? prev : t; });
    };
    const iv = window.setInterval(tick, 60000);
    const onVis = () => { if (!document.hidden) tick(); };
    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", onVis);
    return () => { window.clearInterval(iv); window.removeEventListener("focus", tick); document.removeEventListener("visibilitychange", onVis); };
  }, [asOfPinned]);

  // ── derived ─────────────────────────────────────────────────────────────
  const activeCalendar: HolidayCalendar | null = useMemo(
    () => payload?.calendar || holidayCalendars[calendarId] || null,
    [payload, holidayCalendars, calendarId]
  );
  const selectedMilestone: TnaMilestone | null = useMemo(
    () => payload?.milestones.find((m) => m.code === selectedCode) || null,
    [payload, selectedCode]
  );
  const categories = useMemo(() => template?.categories || [], [template]);
  const pendingCount = intakeSummary?.pending ?? notifications.filter((n) => n.status === "detected").length;
  const currentOrder = useMemo(
    () => orders.find((o) => o.order_id === orderId),
    [orders, orderId]
  );

  // ── write path (preview-first, then confirm) ─────────────────────────────
  const onSubmitUpdate = useCallback(async (m: TnaMilestone, v: UpdateFormValue) => {
    setWriteBusy(true);
    try {
      const res = await updateMilestone({
        order_id: orderId, code: m.code, ...v, apply: false, actor: ACTOR, as_of: asOf, calendar: calendarId,
      });
      const u = unwrap<UpdateResult>(res);
      if (u.error || !u.data) addToast({ kind: "error", message: u.error || "Could not prepare the change" });
      else { setPreviewOrigin(v); setPreview(u.data); }
    } catch (e: any) {
      addToast({ kind: "error", message: e?.message || "Request failed" });
    } finally {
      setWriteBusy(false);
    }
  }, [orderId, asOf, calendarId, addToast]);

  const refreshAfterWrite = useCallback(async () => {
    await Promise.all([loadCalendar(), loadAudit(orderId), loadRag()]);
  }, [loadCalendar, loadAudit, orderId, loadRag]);

  const onConfirmPreview = useCallback(async () => {
    if (!preview) return;
    setWriteBusy(true);
    const actionId = preview.action_id;
    try {
      const res = await runAction(actionId, { as_of: asOf, calendar: calendarId });
      const u = unwrap<UpdateResult>(res);
      if (u.error || !u.data) addToast({ kind: "error", message: u.error || "Could not apply the change" });
      else {
        const code = u.data.code || preview.code;
        /* the ERP owns the plan when it has an Order TNA for this order — mirror the edit there */
        let where = "Kept in the calendar.";
        try {
          const o: any = previewOrigin || {};
          const pr = await pushMilestoneToErp({
            order_id: orderId, code, label: (preview as any).label || (preview as any).name || "",
            actual_date: o.actual_finish || o.actual_start, revised_date: o.revised_finish,
            status: o.status_override, remarks: o.note,
          });
          const pd: any = pr?.data || {};
          if (pd.ok && pd.erp === "written") where = `Also saved in the ERP (${pd.milestone}).`;
          else if (pd.ok === false) where = `Kept in the calendar — the ERP refused it: ${pd.error || "unknown reason"}.`;
          else if (pd.note) where = pd.note;
        } catch { /* the calendar edit stands even when the ERP push fails */ }
        addToast({
          kind: "success",
          message: `Recorded ${code}. ${where}`,
          actionLabel: "Undo",
          onAction: async () => {
            const rb = await rollbackAction(actionId, { as_of: asOf, calendar: calendarId });
            const ru = unwrap<UpdateResult>(rb);
            if (ru.error) addToast({ kind: "error", message: ru.error });
            else addToast({ kind: "info", message: `Rolled back ${code}.` });
            await refreshAfterWrite();
          },
        });
      }
    } catch (e: any) {
      addToast({ kind: "error", message: e?.message || "Request failed" });
    } finally {
      setPreview(null); setPreviewOrigin(null); setWriteBusy(false);
      await refreshAfterWrite();
    }
  }, [preview, previewOrigin, orderId, asOf, calendarId, addToast, refreshAfterWrite]);

  // ── activity actions ────────────────────────────────────────────────────
  const doRun = useCallback(async (a: ActionRecord) => {
    setBusyActionId(a.action_id);
    try {
      const res = await runAction(a.action_id, { as_of: asOf, calendar: calendarId });
      const u = unwrap<UpdateResult>(res);
      if (u.error) addToast({ kind: "error", message: u.error });
      else addToast({ kind: "success", message: `Applied action on ${a.milestone_code}.` });
      await refreshAfterWrite();
    } catch (e: any) {
      addToast({ kind: "error", message: e?.message || "Request failed" });
    } finally { setBusyActionId(null); }
  }, [asOf, calendarId, addToast, refreshAfterWrite]);

  const doRollback = useCallback(async (a: ActionRecord) => {
    setBusyActionId(a.action_id);
    try {
      const res = await rollbackAction(a.action_id, { as_of: asOf, calendar: calendarId });
      const u = unwrap<UpdateResult>(res);
      if (u.error) addToast({ kind: "error", message: u.error });
      else addToast({ kind: "info", message: `Rolled back action on ${a.milestone_code}.` });
      await refreshAfterWrite();
    } catch (e: any) {
      addToast({ kind: "error", message: e?.message || "Request failed" });
    } finally { setBusyActionId(null); }
  }, [asOf, calendarId, addToast, refreshAfterWrite]);

  // ── intake decisions (the bridge: approve → start the TnA) ───────────────
  const doDecide = useCallback(async (id: string, decision: "approve" | "reject" | "snooze") => {
    setIntakeBusyId(id);
    try {
      const fn = decision === "approve" ? approveTnaOrder : decision === "reject" ? rejectTnaOrder : snoozeTnaOrder;
      const res = await fn({ order_id: id, actor: ACTOR });
      const u = unwrap<any>(res);
      if (u.error) addToast({ kind: "error", message: u.error });
      else if (decision === "approve") {
        addToast({
          kind: "success",
          message: `Approved — ${id} is now live in the TnA calendar.`,
        });
        if (u.data?.tower_warning) addToast({ kind: "info", message: `Tower note: ${u.data.tower_warning}` });
        setOrderId(id);
        setView("plan");
        setInboxOpen(false);
      } else {
        addToast({ kind: "info", message: u.data?.message || `Order ${id} updated.` });
      }
      await Promise.all([loadIntake(true), loadStatic(), loadRag(), loadCalendar()]);
    } catch (e: any) {
      addToast({ kind: "error", message: e?.message || "Request failed" });
    } finally { setIntakeBusyId(null); }
  }, [loadIntake, loadStatic, loadRag, loadCalendar, addToast]);

  const onSelect = useCallback((code: string) => setSelectedCode(code), []);
  const onOpenOrder = useCallback((id: string) => { setOrderId(id); setView("plan"); }, []);

  // ── save the Cortex Tower URL (enables the cross-app jump) ───────────────
  const onSaveTowerUrl = useCallback(async (url: string) => {
    setSavingTowerUrl(true);
    try {
      const res = await setTowerLink({ url, actor: ACTOR });
      const u = unwrap<{ ok?: boolean; message?: string }>(res);
      if (u.error) addToast({ kind: "error", message: u.error });
      else {
        addToast({ kind: "success", message: u.data?.message || "Cortex Tower link saved." });
        await loadIntake(false);
      }
    } catch (e: any) {
      addToast({ kind: "error", message: e?.message || "Could not save the link" });
    } finally { setSavingTowerUrl(false); }
  }, [addToast, loadIntake]);

  const onCopyDigest = useCallback(async () => {
    setDigestBusy(true);
    try {
      const res = await getTnaAlerts({ order_id: orderId, calendar: calendarId, as_of: asOf, include_digest: true });
      const u = unwrap<{ digest?: string }>(res);
      const text = u.data?.digest;
      if (!text) { addToast({ kind: "error", message: u.error || "No digest returned" }); return; }
      try {
        await navigator.clipboard.writeText(text);
        addToast({ kind: "success", message: "Reminder digest copied to the clipboard." });
      } catch {
        addToast({ kind: "info", message: text.slice(0, 240) + (text.length > 240 ? " …" : "") });
      }
    } catch (e: any) {
      addToast({ kind: "error", message: e?.message || "Request failed" });
    } finally { setDigestBusy(false); }
  }, [orderId, calendarId, asOf, addToast]);

  // ── render ──────────────────────────────────────────────────────────────
  const isPlan = view === "plan";
  const anyRail = isPlan && (leftRail || rightRail);

  const body = () => {
    if (!payload) {
      if (loading) return <div className="loading-wrap"><span className="spinner" /> Loading TnA plan…</div>;
      if (!ordersLoaded) return <div className="loading-wrap"><span className="spinner" /> Reading the order book from the ERP…</div>;
      if (orders.length === 0) {
        return (
          <EmptyState
            title="No orders in the ERP yet"
            message={ordersError
              ? `${ordersError} Nothing is shown from a stored sample: the plan is only ever built from the Sales Orders in the ERP.`
              : "The Time and Action plan is built from the Sales Orders in the ERP. The moment an order is submitted there it appears in this list and in the new-order inbox, with nothing to import by hand."}
          />
        );
      }
      if (error) { const fe = friendlyError(error); return <EmptyState title={fe.title} message={fe.detail} />; }
      return <EmptyState title="Pick an order" message="Choose an order on the left to load its Time and Action plan." />;
    }
    switch (view) {
      case "plan":
        return <PlanView payload={payload} calendar={activeCalendar} categories={categories} onSelect={onSelect} />;
      case "board":
        return <BoardView milestones={payload.milestones} onSelect={onSelect} />;
      case "calendar":
        return <CalendarPage
          milestones={payload.milestones}
          shipDate={payload.header.ship_date}
          asOf={payload.as_of}
          holidayCalendars={holidayCalendars}
          activeCalendarId={payload.calendar?.calendar || calendarId}
          onSelect={onSelect}
        />;
      case "program":
        return <Program asOf={payload.as_of} calendar={payload.calendar?.calendar || calendarId} onOpen={onOpenOrder} />;
      case "template":
        return <Template template={template} />;
      case "activity":
        return <Activity logs={audit.logs} actions={audit.actions} onRun={doRun} onRollback={doRollback} busyId={busyActionId} />;
      default:
        return null;
    }
  };

  return (
    <div className="app-shell">
      <TopBar
        view={view}
        onNav={setView}
        orderLabel={currentOrder ? `${currentOrder.order_id} · ${currentOrder.customer || "—"}` : ""}
        calendars={Object.keys(holidayCalendars).length ? Object.keys(holidayCalendars) : [calendarId]}
        calendarId={calendarId}
        onCalendarChange={setCalendarId}
        asOf={asOf}
        onAsOfChange={setAsOfManual}
        asOfPinned={asOfPinned}
        onResetAsOf={resetAsOfToday}
        source={payload?.source ?? null}
        apiStatus={apiStatus}
        loading={loading}
        onRefresh={() => { loadCalendar(); loadIntake(true); loadRag(); }}
        pendingCount={pendingCount}
        onOpenInbox={() => setInboxOpen(true)}
        towerUrl={bridge?.tower_jump_enabled ? (bridge?.tower_app_url || null) : null}
        railsOpen={isPlan && (leftRail || rightRail)}
        onToggleRails={() => { const open = leftRail || rightRail; setLeftRail(!open); setRightRail(!open); }}
      />

      <div className={`app-body${anyRail ? " with-rails" : ""}`}>
        {isPlan && (leftRail ? (
          <OrderRail
            orders={orders}
            orderId={orderId}
            onSelect={setOrderId}
            ragByOrder={ragByOrder}
            onClose={() => setLeftRail(false)}
          />
        ) : (
          <button className="rail-handle rail-handle--left" onClick={() => setLeftRail(true)}
            title="Show orders panel" aria-label="Show orders panel">
            <ChevronRight size={16} />
            <span>Orders</span>
          </button>
        ))}

        <main className="content">
          <div className="stack">
            <OfflineBanner status={apiStatus} hasData={!!payload} />
            {error && payload && (
              <div className="banner banner-error">
                <span className="banner-icon">⚠</span>
                <div><div className="banner-title">Refresh failed</div><div>{error} — showing last loaded data.</div></div>
              </div>
            )}
            {payload && <DataQualityBanner issues={payload.data_quality} />}
            <div id="page-body">{body()}</div>
          </div>
        </main>

        {isPlan && payload && (rightRail ? (
          <NeedsAttentionRail
            exceptions={payload.exceptions}
            alerts={payload.alerts || []}
            onSelect={onSelect}
            onCopyDigest={onCopyDigest}
            digestBusy={digestBusy}
            onClose={() => setRightRail(false)}
          />
        ) : (
          <button className="rail-handle rail-handle--right" onClick={() => setRightRail(true)}
            title="Show needs-attention panel" aria-label="Show needs-attention panel">
            <span>Needs attention</span>
            <ChevronLeft size={16} />
          </button>
        ))}
      </div>

      {inboxOpen && (
        <div className="slideover-scrim" onClick={() => setInboxOpen(false)}>
          <div className="slideover" onClick={(e) => e.stopPropagation()}>
            <button className="slideover-close" onClick={() => setInboxOpen(false)} aria-label="Close">✕</button>
            <IntakePanel
              notifications={notifications}
              summary={intakeSummary}
              bridge={bridge}
              error={intakeError}
              busyId={intakeBusyId}
              onApprove={(id) => doDecide(id, "approve")}
              onReject={(id) => doDecide(id, "reject")}
              onSnooze={(id) => doDecide(id, "snooze")}
              onOpen={(id) => { setOrderId(id); setView("plan"); setInboxOpen(false); }}
              onSaveTowerUrl={onSaveTowerUrl}
              savingUrl={savingTowerUrl}
            />
          </div>
        </div>
      )}

      <MilestoneDetailDrawer
        milestone={selectedMilestone}
        milestones={payload?.milestones || []}
        onClose={() => setSelectedCode(null)}
        onSubmitUpdate={onSubmitUpdate}
        onSelectCode={(c) => setSelectedCode(c)}
        busy={writeBusy && !preview}
      />

      {preview && (
        <ConfirmPreviewModal
          preview={preview}
          onConfirm={onConfirmPreview}
          onCancel={() => { setPreview(null); setPreviewOrigin(null); }}
          busy={writeBusy}
        />
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
