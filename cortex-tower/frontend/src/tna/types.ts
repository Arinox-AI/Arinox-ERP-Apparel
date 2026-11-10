// Cortex TnA Calendar — domain types (mirror the backend JSON contracts in
// backend/document.md + SPEC.md §5.3). Nothing here is stored; all objects are
// computed live by the backend and rendered read-only.

export type Rag = "red" | "amber" | "green";
export type Source = "live" | "snapshot" | "sample" | "unavailable";
export type StatusSource = "computed" | "override";

/** The 10-value closed status vocabulary (SPEC §8.1). */
export const STATUS_VOCAB = [
  "Not started",
  "In progress",
  "Waiting for approval",
  "Waiting for material",
  "Completed",
  "Completed late",
  "At risk",
  "Blocked",
  "Overdue",
  "Not recorded",
] as const;
export type Status = (typeof STATUS_VOCAB)[number];

/** The 14 standard delay causes (SPEC §8.6). */
export const DELAY_CAUSES = [
  "Late buyer comments",
  "Late sample approval",
  "Fabric mill delay",
  "Trim supplier delay",
  "Material quality failure",
  "Shade/shrinkage problem",
  "Capacity shortage",
  "Machine breakdown",
  "Labour shortage",
  "Rework",
  "Failed inspection",
  "Weather/transport",
  "Documentation",
  "Vessel/forwarder delay",
] as const;

export interface TnaHeader {
  order_id: string;
  sales_order_status: string | null;
  docstatus: number;
  customer: string | null;
  customer_legal: string | null;
  company: string | null;
  po_no: string | null;
  client_po_no: string | null;
  po_date: string | null;
  style_no: string | null;
  style_name: string | null;
  colour: string | null;
  qty: number | null;
  sizes: Record<string, number> | null;
  order_value: number | null;
  currency: string | null;
  site: string | null;
  ship_date: string | null;
  days_to_ship: number;
  overall_status: string;
  rag: Rag;
  calendar: string;
  product_type: string;
  template_id: string;
  source: Source;
}

export interface TnaMilestone {
  seq: number;
  code: string;
  name: string;
  category: string;
  owner_role: string;
  planned_start: string | null;
  planned_finish: string | null;
  actual_start: string | null;
  actual_finish: string | null;
  status: string;
  delay_days: number;
  delay_reason: string | null;
  is_critical: boolean;
  is_critical_template?: boolean;
  on_critical_path?: boolean;
  float_days?: number | null;
  calendar?: string;
  progress_pct?: number;
  forecast_finish?: string | null;
  revised_finish?: string | null;
  manual?: boolean;
  depends_on: string[];
  evidence_source: string | null;
  evidence_value: string | null;
  offset_days: number;
  duration_days: number;
  requires_approval: boolean;
  is_blocked: boolean;
  blocked_by: string[];
  status_source: StatusSource | string;
  needs_attribution: boolean;
  owner: string;
  note: string | null;
  evidence_retrieved: boolean;
  data_source: string;
  updated_at: string | null;
  status_override?: string | null;
}

export interface TnaNextAction {
  code: string;
  name: string;
  owner_role: string;
  status: string;
  delay_days: number;
  next_action_text: string;
}

export interface TnaKpi {
  on_time_pct: number;
  completed_count: number;
  completed_on_time_count: number;
  completed_late_count: number;
  overdue_count: number;
  at_risk_count: number;
  blocked_count: number;
  waiting_approval_count: number;
  waiting_material_count: number;
  in_progress_count: number;
  not_started_count: number;
  not_recorded_count: number;
  total_milestones: number;
  critical_total: number;
  critical_completed_count: number;
  critical_late_count: number;
  critical_path_delay_days: number;
  days_to_ship: number;
  ship_overdue_days: number;
  latest_actual_finish: string | null;
  latest_critical_actual_finish: string | null;
  projected_ship_date: string | null;
  required_ship_date: string | null;
  projected_slip_days: number;
  on_time_vs_required: string;
  un_attributed_lates: number;
  progress_pct: number;
  erp_linked_count: number;
  manual_count: number;
  alert_count?: number;
  alert_critical_count?: number;
  max_escalation?: number;
  rag: Rag;
  next_action: TnaNextAction | null;
  source: Source;
}

export interface HolidayCalendar {
  calendar: string;
  label: string;
  country: string;
  tz: string;
  year: number;
  working_weekdays: number[];
  working_week_label: string;
  holidays: Record<string, string>;
  special_working_days: string[];
  source: string;
  note: string;
  weekday_numbering?: string;
}

export interface TnaTemplateMilestone {
  seq: number;
  code: string;
  name: string;
  category: string;
  owner_role: string;
  offset_days: number;
  duration_days: number;
  depends_on: string[];
  is_critical: boolean;
  requires_approval: boolean;
  evidence_source: string;
  calendar?: string;
}

export interface TnaTemplate {
  template_id: string;
  product_type: string;
  description: string;
  calendar: string;
  anchor: string;
  schedule_direction: string;
  categories: string[];
  owner_roles: string[];
  milestone_count: number;
  milestones: TnaTemplateMilestone[];
  source: string;
}

/** An exception row = a milestone enriched with ranking metadata (§10). */
export interface ExceptionRow extends TnaMilestone {
  next_action_text: string;
  rank_reason: string;
}

export interface DataQualityIssue {
  issue: string;
  erp_note: string;
  affected_code?: string;
}

export interface TemplateSummary {
  template_id: string;
  product_type: string;
  milestone_count: number;
}

export interface TnaCalendar {
  source: Source;
  generated_at: string;
  as_of: string;
  header: TnaHeader;
  milestones: TnaMilestone[];
  kpis: TnaKpi;
  exceptions: ExceptionRow[];
  alerts?: AlertItem[];
  alert_summary?: AlertSummary;
  owners?: OwnersBlock;
  calendar: HolidayCalendar;
  template: TemplateSummary;
  data_quality: DataQualityIssue[];
  warnings: string[];
}

// ── Alerts / escalation (get_tna_alerts, get_tna_owners) ────────────────────
export type AlertSeverity = "critical" | "high" | "medium" | "low";

export interface AlertItem {
  code: string;
  name: string;
  category: string;
  seq: number;
  kind: string;
  severity: AlertSeverity;
  status: string;
  owner: string | null;
  owner_role: string;
  assigned_to: string;
  is_critical: boolean;
  manual: boolean;
  planned_finish: string | null;
  actual_finish: string | null;
  forecast_finish: string | null;
  days_open: number;
  delay_days: number;
  escalation_level: number;
  escalate_to: string | null;
  tags: string[];
  next_action_text: string;
  evidence_source: string | null;
}

export interface AlertSummary {
  total: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  by_kind: Record<string, number>;
  escalation_level_1: number;
  escalation_level_2: number;
  escalation_level_3: number;
  unassigned: number;
  manual: number;
  missing_reason: number;
  max_escalation: number;
  top_owner: string | null;
  milestones_total: number;
}

export interface OwnerWorkload {
  owner: string;
  role: string;
  total: number;
  completed: number;
  open: number;
  overdue: number;
  at_risk: number;
  blocked: number;
  awaiting: number;
  critical: number;
  manual: number;
  progress_pct: number;
  codes: string[];
}

export interface OwnersBlock {
  owners: OwnerWorkload[];
  total: number;
  unassigned: OwnerWorkload | null;
}

export interface AlertsResponse {
  order_id: string;
  as_of: string;
  source: Source;
  header: TnaHeader;
  alerts: AlertItem[];
  summary: AlertSummary;
  owners: OwnersBlock;
  kpis: TnaKpi;
  digest?: string;
  warnings: string[];
}

// ── Multi-order / capacity (get_tna_program) ────────────────────────────────
export interface ProgramOrder {
  order_id: string;
  customer: string | null;
  customer_legal: string | null;
  style_no: string | null;
  style_name: string | null;
  qty: number | null;
  currency: string | null;
  order_value: number | null;
  ship_date: string | null;
  days_to_ship: number | null;
  rag: Rag;
  overall_status: string;
  sales_order_status: string | null;
  overdue_count: number;
  at_risk_count: number;
  blocked_count: number;
  progress_pct: number;
  erp_linked_count: number;
  critical_path_delay_days: number;
  alert_count: number;
  max_escalation: number;
  ship_overdue_days?: number;
  source: Source;
  plan_based: boolean;
}

export interface CapacityMonth {
  month: string;
  orders: number;
  qty: number;
  overdue: number;
  red: number;
  amber: number;
  green: number;
}

export interface ProgramResponse {
  as_of: string;
  source: Source;
  detail: boolean;
  orders: ProgramOrder[];
  total_orders: number;
  qty_total: number;
  by_rag: { red: number; amber: number; green: number };
  orders_ship_past: number;
  orders_ship_within_horizon: number;
  horizon_wd: number;
  capacity_by_ship_month: CapacityMonth[];
  warnings: string[];
}

export interface TnaOrder {
  order_id: string;
  customer: string | null;
  style_no: string | null;
  style_name: string | null;
  colour: string | null;
  qty: number | null;
  ship_date: string | null;
  sales_order_status: string | null;
  product_type: string;
  template_id: string;
  source: Source;
}

export interface TnaOrdersResponse {
  orders: TnaOrder[];
  total: number;
  total_count: number;
  offset: number;
  limit: number;
  source: Source;
  warnings: string[];
}

export interface TnaKpisResponse {
  order_id: string;
  as_of: string;
  source: Source;
  kpis: TnaKpi;
  warnings: string[];
}

export interface HolidaysResponse {
  calendars: Record<string, HolidayCalendar>;
  available: string[];
  source: string;
  year: number;
}

export interface MilestoneChange {
  field: string;
  old: string;
  new: string;
}

export interface UpdateResult {
  mode: "preview" | "applied" | "rolled_back";
  action_id: string;
  order_id: string;
  code: string;
  changes: MilestoneChange[];
  status_before: string | null;
  status_after: string | null;
  rag_before?: Rag | null;
  rag_after?: Rag | null;
  write_target?: string;
  erp_write: boolean;
  mode_gate: string;
  requires_confirmation?: boolean;
  reversible?: boolean;
  restored?: boolean;
  record?: Record<string, any> | null;
  source: Source;
  error?: string;
}

export interface ActionRecord {
  id: number;
  action_id: string;
  order_id: string;
  milestone_code: string;
  kind: string;
  before: Record<string, any> | null;
  after: Record<string, any> | null;
  changes: MilestoneChange[];
  mode: string;
  status: "staged" | "applied" | "rolled_back" | string;
  actor: string;
  created_at: string | null;
  applied_at: string | null;
  rolled_back_at: string | null;
}

export interface AuditEntry {
  id: number;
  action_id: string;
  order_id: string;
  milestone_code: string;
  action_type: string;
  status: string;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  changes: MilestoneChange[];
  reason: string | null;
  actor: string;
  mode: string;
  source: Source;
  created_at: string | null;
}

export interface AuditResponse {
  logs: AuditEntry[];
  total: number;
  total_count: number;
  offset: number;
  limit: number;
  actions: ActionRecord[];
  actions_total: number;
}

// ── New-order intake + Cortex Tower bridge ──────────────────────────────────
export interface TowerContext {
  tower_status?: string | null;
  tower_rag?: Rag | null;
  tower_buyer?: string | null;
  tower_po_no?: string | null;
  tower_value?: number | null;
  tower_currency?: string | null;
  tower_style?: string | null;
  tower_risk_count?: number;
  tower_risk_titles?: { title: string; severity?: string }[];
}

export type IntakeStatus = "detected" | "approved" | "rejected" | "snoozed";

export interface IntakeNotification {
  id: number;
  order_id: string;
  customer: string | null;
  style_no: string | null;
  style_name: string | null;
  qty: number | null;
  ship_date: string | null;
  product_type: string | null;
  status: IntakeStatus;
  source: string;
  tower_ref: string | null;
  tower_context: TowerContext | null;
  note: string | null;
  actor: string | null;
  detected_at: string | null;
  decided_at: string | null;
  /** deep link into the Cortex Tower for this order (null when no URL is configured) */
  tower_link?: string | null;
}

export interface IntakeSummary {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  snoozed: number;
  from_tower: number;
}

export interface BridgeStatus {
  tower_project: string;
  tower_configured: boolean;
  tower_functions: string[];
  /** Cortex Tower app URL used by the "Open in Cortex Tower" jump (null = not set) */
  tower_app_url?: string | null;
  tower_jump_enabled?: boolean;
  tower_url_source?: "env" | "saved" | null;
  erp: { connected: boolean; base: string | null; error: string | null };
  note: string;
  generated_at?: string;
}

export interface SetTowerLinkResult {
  ok?: boolean;
  tower_app_url?: string | null;
  jump_enabled?: boolean;
  message?: string;
  error?: string;
}

export interface IntakeResponse {
  notifications: IntakeNotification[];
  summary: IntakeSummary;
  bridge: BridgeStatus;
  generated_at?: string;
  error?: string;
}

export interface IntakeDecision {
  order_id: string;
  decision: string;
  status: string;
  started: boolean;
  record: IntakeNotification;
  tower_notified: boolean;
  tower_warning?: string;
  message: string;
  error?: string;
}
