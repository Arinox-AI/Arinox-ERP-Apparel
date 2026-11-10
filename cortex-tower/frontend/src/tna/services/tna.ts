// Typed wrappers around the backend functions. Every call goes through callApi
// (the KOGO middleware at API_BASE) — no other transport exists in this app.
import { callApi, type ApiResponse } from "./api";

export interface Unwrapped<T> {
  data: T | null;
  error: string | null;
}

/** Unwrap a middleware ApiResponse: surfaces backend error dicts as `error`. */
export function unwrap<T>(res: ApiResponse): Unwrapped<T> {
  if (!res || res.success === false) {
    return { data: null, error: res?.message || res?.diagnosis?.suggested_fix || "Request failed" };
  }
  const d = res.data as any;
  if (d && typeof d === "object" && "error" in d && d.error) {
    return { data: null, error: String(d.error) };
  }
  return { data: (d as T) ?? null, error: null };
}

export interface CalendarParams {
  order_id?: string;
  calendar?: string;
  product_type?: string;
  as_of?: string;
  force_snapshot?: boolean;
}

export const getTnaCalendar = (params: CalendarParams = {}) =>
  callApi("get_tna_calendar", params);

export const getTnaOrders = (params: { product_type?: string; search_query?: string; limit?: number; offset?: number; force_snapshot?: boolean } = {}) =>
  callApi("get_tna_orders", params);

export const getTnaTemplate = (params: { product_type?: string; template_id?: string } = {}) =>
  callApi("get_tna_template", params);

export const getHolidays = (params: { calendar?: string } = {}) =>
  callApi("get_holidays", params);

export const getTnaKpis = (params: CircleParams = {}) =>
  callApi("get_tna_kpis", params);

interface CircleParams {
  order_id?: string;
  calendar?: string;
  as_of?: string;
  force_snapshot?: boolean;
}

export interface UpdateMilestoneParams {
  order_id?: string;
  code: string;
  actual_start?: string;
  actual_finish?: string;
  revised_finish?: string;
  delay_reason?: string;
  owner?: string;
  note?: string;
  status_override?: string;
  apply?: boolean;
  actor?: string;
  as_of?: string;
  calendar?: string;
  force_snapshot?: boolean;
}

export const updateMilestone = (params: UpdateMilestoneParams) =>
  callApi("update_milestone", params);

/** After a calendar edit is recorded: write it to the ERP's TNA Milestone too, when the order has an
 *  Order TNA there. The answer says plainly where the edit lives ("written" / kept in the calendar). */
export const pushMilestoneToErp = (p: { order_id: string; code: string; label?: string; actual_date?: string;
  revised_date?: string; status?: string; remarks?: string }) => {
  const clean = (v?: string) => (v && v !== "__clear__" ? v : "");
  return callApi("cx_tna_push_milestone", {
    order_id: p.order_id, code: p.code, label: p.label || "", actual_date: clean(p.actual_date),
    revised_date: clean(p.revised_date), status: clean(p.status), remarks: clean(p.remarks),
  });
};

// NOTE: ``run_action`` / ``rollback_action`` / ``get_audit_log`` collide with
// Control Tower functions, so the merged backend publishes the TnA variants
// under a ``tna_`` prefix (see backend/functions.py).
export const runAction = (action_id: string, params: { as_of?: string; calendar?: string; force_snapshot?: boolean } = {}) =>
  callApi("tna_run_action", { action_id, ...params });

export const rollbackAction = (action_id: string, params: { as_of?: string; calendar?: string; force_snapshot?: boolean } = {}) =>
  callApi("tna_rollback_action", { action_id, ...params });

export const getAuditLog = (params: { order_id?: string; action_id?: string; limit?: number; offset?: number } = {}) =>
  callApi("tna_get_audit_log", params);

export const getTnaAlerts = (params: { order_id?: string; as_of?: string; calendar?: string; force_snapshot?: boolean; include_digest?: boolean } = {}) =>
  callApi("get_tna_alerts", params);

export const getTnaOwners = (params: { order_id?: string; as_of?: string; calendar?: string; force_snapshot?: boolean } = {}) =>
  callApi("get_tna_owners", params);

export const getTnaProgram = (params: { as_of?: string; horizon_wd?: number; limit?: number; calendar?: string; force_snapshot?: boolean; detail?: boolean; search_query?: string } = {}) =>
  callApi("get_tna_program", params);

// ── New-order intake + Cortex Tower bridge ──────────────────────────────────
export const getTnaIntake = (params: { status?: string; sync?: boolean; force?: boolean } = {}) =>
  callApi("get_tna_intake", params);

export const approveTnaOrder = (params: { order_id: string; actor?: string; note?: string }) =>
  callApi("approve_tna_order", params);

export const rejectTnaOrder = (params: { order_id: string; actor?: string; note?: string }) =>
  callApi("reject_tna_order", params);

export const snoozeTnaOrder = (params: { order_id: string; actor?: string; note?: string }) =>
  callApi("snooze_tna_order", params);

export const getBridgeStatus = () => callApi("get_bridge_status", {});

export const setTowerLink = (params: { url: string; actor?: string }) =>
  callApi("set_tower_link", params);
