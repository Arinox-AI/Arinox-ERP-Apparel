export type View = "wip" | "tna" | "overview" | "orders" | "risks" | "actions" | "operations" | "forecast" | "fabric" | "activity" | "mail" | "inbox" | "intake" | "enquiries";

/* ── Fabric & price intelligence (live from get_fabric_intelligence) ──────── */
export interface FabricFlag { style: string; type: string; severity: string; title: string; detail: string; impact_usd?: number | null; }
export interface FabricRow {
  style: string; description?: string | null; fabric_item?: string | null; fabric_content?: string | null;
  gsm?: number | null; vendor?: string | null;
  order_qty_pcs?: number | null; order_value_usd?: number | null; sell_price_usd?: number | null;
  client_po_price_usd?: number | null; client_po_numbers?: string[]; sales_orders?: string[];
  consumption_yd: { bom?: number | null; costing?: number | null; costing_with_3pct?: number | null;
                    client_po?: number | null; consensus?: number | null; spread_pct?: number | null; sources?: number };
  required_m_unit: { bom?: number | null; costing?: number | null };
  required_m_total: { bom?: number | null; costing?: number | null; with_3pct?: number | null };
  rate_usd: { buy_per_yd?: number | null; buy_per_m?: number | null; buy_uom?: string | null; po?: string | null;
              supplier?: string | null; quoted_per_yd?: number | null; allowed_per_garment?: number | null };
  cost_usd: Record<string, number | null>;
  margin_usd?: number | null; margin_pct?: number | null;
  fabric_exposure_usd?: number | null; consumption_gap_usd?: number | null;
  flags: string[]; verdict: string;
}
export interface FabricIntel {
  summary: Record<string, any>; rows: FabricRow[]; flags: FabricFlag[];
  charts: { consumption_sources: any[]; cost_vs_price: any[]; fabric_value_by_style: any[]; flags_by_type: any[] };
  meta?: Record<string, number>;
  live?: boolean; source?: string; generated_at?: string; connection?: Connection; error?: string;
}

/** Verdict → badge class + label. */
export const VERDICT: Record<string, { cls: string; label: string }> = {
  ok:    { cls: "badge--positive", label: "OK" },
  watch: { cls: "badge--warning",  label: "Watch" },
  alert: { cls: "badge--critical", label: "Alert" },
};

/** Human label for each detection flag. */
export const FABRIC_FLAG_LABEL: Record<string, string> = {
  consumption_conflict: "Consumption conflict", rate_drift: "Fabric price moved",
  price_below_cost: "Below cost", thin_margin: "Thin margin",
  missing_bom: "No BOM", missing_costing: "No costing", no_buy_rate: "Not purchased",
  po_vs_so_price: "PO vs SO price", uom_mix: "Unit mix",
};

export interface Kpi { key: string; label: string; value: string; unit: string; tone: string; hint?: string; tooltip?: string; }

export interface Risk {
  id: number; risk_key?: string; risk_type: string; severity: string; title: string; material?: string;
  required_qty?: string; affected_orders?: string[]; required_date?: string;
  production_line?: string; planned_output?: string; actual_output?: string; style?: string;
  defect_rate?: string; inspection_stage?: string; affected_order?: string; shipment_date?: string;
  vessel?: string; expected_delay?: string; expected_margin?: string; current_margin?: string;
  cost_variance?: string; status: string;
  created_at?: string; updated_at?: string;
  ai?: AiSuggestion;
}

/** Grounded AI next-step plan attached to a risk (Phase 3). */
export interface AiSuggestion {
  risk_key: string;
  reasoning?: string;
  summary?: string;
  actions?: { action?: string; why?: string; owner?: string; priority?: string; confidence?: number }[];
  predicted_impact?: string;
  watch_outs?: string;
  source?: string;
  grounded?: boolean;
  unsourced?: string[];
  created_at?: string;
}

export interface Rec {
  id: number; risk_id: number; risk_title: string; action: string; expected_impact: string;
  responsible_team: string; priority: string; approval_status: string; modified_text?: string;
  action_key?: string; risk_key?: string; executed_at?: string;
  write_status?: string; result_doctype?: string; result_doc?: string;
  erp_url?: string; erp_list_url?: string; erp_doctype?: string;
}

/* ── Outbound mail (approval queue) ───────────────────────────────────────── */
export interface EmailDraft {
  id: number;
  action_id?: number | null;
  action_key?: string;
  intent?: string;
  to_email?: string;
  from_name?: string;
  subject?: string;
  body?: string;
  status: string;
  grounding_ok?: number | boolean;
  grounding_unsourced?: string[] | string;
  policy_version?: string;
  edited?: number | boolean;
  message_id?: string | null;
  error?: string | null;
  created_at?: string;
  decided_at?: string | null;
  sent_at?: string | null;
  decided_by?: string;
}

export interface MailSettings {
  enabled?: number | boolean;
  email_account?: string;
  from_name?: string;
  smtp_host?: string;
  smtp_port?: number;
  use_tls?: number | boolean;
  password_set?: boolean;
  /** false = a password is stored but can't be unlocked (the key changed) — it must be typed again */
  password_readable?: boolean;
  updated_at?: string;
}

export interface Audit {
  id: number; action_type: string; action_name: string; description: string; actor: string;
  risk_title?: string; approved?: string; timestamp: string;
}

export interface Connection { connected: boolean; base: string; error: string | null; }

export interface Dashboard {
  kpis: Kpi[]; risks: Risk[]; recommendations: Rec[]; audit_log: Audit[]; buyer_orders: any[];
  charts: Record<string, any[]>; factories: string[]; date_options: string[];
  command_suggestions: string[]; demo: boolean;
  live?: boolean;
  write_mode?: string;
  source?: string;
  connection?: Connection;
  generated_at?: string;
  risk_summary?: { total: number; critical: number; warning: number; info: number; all_clear: boolean };
  forecast?: Forecast;
  migration_gaps?: { gap_key?: string; process_area?: string; status?: string; missing?: string }[];
  /** The ERP model census (backend/erp_model.py) — what the ERP holds today. */
  erp_model?: ErpModel;
  /** The customs leg, grouped per shipment (never per evidence row). */
  shipment_leg?: ShipmentLeg;
}

export interface ErpModelObject {
  doctype: string; purpose: string; count: number;
  status: "populated" | "empty" | "missing" | string;
}
export interface ErpModelStage { key: string; label: string; objects: ErpModelObject[]; populated: number; total: number }
export interface ErpModel {
  generated_at?: string;
  stages: ErpModelStage[];
  totals: { objects: number; populated: number; empty: number; missing: number; rows: number };
  retired?: { retired: string; use: string }[];
}
export interface ShipmentLeg {
  groups: any[]; evidence_rows: number; shipped_pcs: number; ordered_pcs: number;
  groups_with_qty: number; allowance_flags: string[];
  groups_missing_documents: string[]; unlinked_rows: string[];
}

export interface Forecast {
  delivery?: any[];
  stockout?: any[];
  margin?: any[];
  margin_unverified?: number;
  cash?: { by_currency?: Record<string, any>; note?: string };
  supplier?: any[];
  open_orders?: number;
  note?: string;
}

/* ── tone helpers ─────────────────────────────────────────────────────────── */

export const toneColor: Record<string, string> = {
  positive: "var(--positive)",
  warning: "var(--warning)",
  critical: "var(--negative)",
  neutral: "var(--text-secondary)",
};

export const sevBg: Record<string, string> = {
  critical: "var(--negative-light)",
  warning: "var(--warning-light)",
};

export const priorityColor: Record<string, string> = {
  high: "var(--negative)",
  medium: "var(--warning)",
  low: "var(--positive)",
};

export const statusBadge: Record<string, { bg: string; fg: string; label: string }> = {
  pending: { bg: "#f1f5f9", fg: "#64748b", label: "Pending" },
  approved: { bg: "var(--positive-light)", fg: "var(--positive-ink)", label: "Approved" },
  rejected: { bg: "var(--negative-light)", fg: "var(--negative-ink)", label: "Rejected" },
  modified: { bg: "var(--warning-light)", fg: "var(--warning-ink)", label: "Modified" },
  executed: { bg: "#e0e7ff", fg: "#3730a3", label: "Executed" },
};

/** Human label + what the action means for each live risk type. */
export const RISK_TYPE_META: Record<string, { label: string; hint: string }> = {
  production_delay: { label: "Production", hint: "Manufacturing / planning" },
  shipment_risk: { label: "Shipment", hint: "Outbound / delivery" },
  quality_risk: { label: "Quality", hint: "Inspection / compliance" },
  fabric_shortage: { label: "Sourcing", hint: "Material availability" },
  margin_risk: { label: "Margin", hint: "Cost / pricing" },
  invoicing_risk: { label: "Invoicing", hint: "Receivables / cash" },
  data_quality: { label: "Data quality", hint: "Evidence / migration" },
  supplier_risk: { label: "Supplier", hint: "Procurement / lead time" },
  logistics_risk: { label: "Logistics", hint: "Documents / customs" },
  compliance_risk: { label: "Compliance", hint: "Invoice vs goods" },
  cash_risk: { label: "Cash", hint: "Payables / payables aging" },
};

export const RISK_ACTIONS: Record<string, string[]> = {
  fabric_shortage: ["Create Material Request", "Email Supplier", "Find Alternative Supplier", "Ask KOGO"],
  production_delay: ["Replan Production", "Reallocate Capacity", "Assign Action", "Ask KOGO"],
  quality_risk: ["Schedule Inspection", "Create Rework Task", "Notify Quality Team", "Ask KOGO"],
  shipment_risk: ["Find Alternative Shipment", "Update Shipment Plan", "Email Buyer", "Ask KOGO"],
  margin_risk: ["Analyse Cost Variance", "Review Material Cost", "Notify Finance", "Ask KOGO"],
  data_quality: ["Ask Cortex for evidence", "Create Follow-up Task", "Notify Data Owner", "Ask KOGO"],
  invoicing_risk: ["Review Receivables", "Post Payment Entry", "Notify Finance", "Ask KOGO"],
};

/** Which risk fields to surface first, in order, in the detail drawer. */
export const RISK_FIELD_ORDER: { key: keyof Risk; label: string }[] = [
  { key: "material", label: "Material" },
  { key: "style", label: "Style" },
  { key: "required_qty", label: "Required qty" },
  { key: "production_line", label: "Production line" },
  { key: "planned_output", label: "Planned output" },
  { key: "actual_output", label: "Actual output" },
  { key: "defect_rate", label: "Defect rate" },
  { key: "inspection_stage", label: "Inspection stage" },
  { key: "affected_order", label: "Affected order" },
  { key: "shipment_date", label: "Shipment date" },
  { key: "vessel", label: "Vessel / carrier" },
  { key: "expected_delay", label: "Variance" },
  { key: "expected_margin", label: "Expected margin" },
  { key: "current_margin", label: "Current margin" },
  { key: "cost_variance", label: "Impact" },
  { key: "required_date", label: "Required date" },
];

/* ── formatters ───────────────────────────────────────────────────────────── */

/* All times are shown in IST (Asia/Kolkata) — the operating timezone for Cortex. */
export const IST_TZ = "Asia/Kolkata";

/** Parse an ISO value. A timezone-less string (no Z / ±HH:MM) is treated as UTC,
 *  because the backend and the local DB store UTC — otherwise the browser would
 *  silently read it as its own local time and show the wrong wall-clock. */
function toDate(iso?: string): Date | null {
  if (!iso) return null;
  let s = String(iso).trim();
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += "Z";
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

export function fmtTime(iso: string) {
  if (!iso) return "";
  const d = toDate(iso);
  if (!d) return iso;
  return d.toLocaleString("en-US", { timeZone: IST_TZ, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) + " IST";
}

export function fmtDate(iso?: string) {
  if (!iso) return "—";
  const d = toDate(iso);
  if (!d) return iso;
  return d.toLocaleDateString("en-US", { timeZone: IST_TZ, year: "numeric", month: "short", day: "numeric" });
}

export function fmtMonth(ym?: string) {
  if (!ym) return "—";
  const d = new Date(`${ym}-01T00:00:00`);
  if (isNaN(d.getTime())) return ym;
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

export function fmtNum(n: any) {
  const v = Number(n);
  if (!isFinite(v)) return String(n ?? "—");
  return v.toLocaleString("en-US");
}

export function sevRank(severity: string) {
  return severity === "critical" ? 0 : 1;
}

/* ── Inbound mail (understood inbox + order-change queue) ─────────────────── */
export interface MailAttachment { filename?: string; mime?: string; size?: number; }
export interface MailMessage {
  id: number;
  uid?: string;
  message_id?: string;
  thread_id?: string;
  from_name?: string;
  from_addr?: string;
  to_addr?: string;
  subject?: string;
  snippet?: string;
  body_text?: string;
  received_at?: string;
  has_attachments?: number;
  attachments?: MailAttachment[];
  classification: string;
  confidence?: number;
  reasons?: string[];
  po_refs?: string[];
  matched_orders?: { so?: string; po_no?: string; customer?: string }[];
  status?: string;
  created_at?: string;
}

export interface OrderChange {
  id: number;
  mail_id?: number | null;
  change_type: string;
  title: string;
  summary?: string;
  from_addr?: string;
  so_name?: string | null;
  po_no?: string | null;
  customer?: string | null;
  severity: string;
  next_steps?: string[];
  status: string;
  result_doctype?: string | null;
  result_doc?: string | null;
  result_note?: string | null;
  needs_action?: boolean;
  erp_doctype?: string | null;
  erp_url?: string | null;
  erp_list_url?: string | null;
  decided_at?: string | null;
  decided_by?: string | null;
  created_at?: string;
}

export interface InboxSummary {
  total_mail: number;
  unread: number;
  by_classification: { key: string; label: string; count: number }[];
  pending_changes: number;
  critical: number;
  live?: boolean;
  source?: string;
}

export const CLASS_LABEL: Record<string, string> = {
  new_order: "New order",
  order_amendment: "Order amendment",
  invoice: "Invoice",
  remittance: "Remittance",
  query: "Query",
  other: "General",
};

export const CLASS_BADGE: Record<string, string> = {
  new_order: "badge--brand",
  order_amendment: "badge--critical",
  invoice: "badge--warning",
  remittance: "badge--positive",
  query: "badge--warning",
  other: "badge--outline",
};


/* ── Intake — a mail understood, and the process it starts ─────────────────── */
export interface IntakeStep {
  seq: number;
  key: string;
  label: string;
  doctype: string;
  status: "ready" | "blocked";
  reason?: string;
  kind?: string;
  depends_on?: string;
  existing?: string;      // a record the site already holds — this step will LINK it
  payload?: Record<string, any>;
}

export interface IntakeRun {
  id: number;
  mail_id: number | null;
  route: string;
  document_type: string;
  status: string;
  summary?: string;
  confidence: Record<string, number>;
  missing: string[];
  blocking: string[];
  created_refs: { doctype: string; name: string; step?: string }[];
  result_note?: string | null;
  extractor?: string;
  decided_by?: string | null;
  decided_at?: string | null;
  created_at?: string | null;
  subject?: string;
  from_addr?: string;
  received_at?: string;
  document_count?: number;
  chain_id?: number | null;
  chain_subject?: string;
  chain_mails?: number;
  chain_customer?: string;
}

export interface IntakeDates {
  received: string;
  po_date: string;
  ship_date: string;
  lead_time_days: number | null;
  po_to_ship_days: number | null;
  days_to_ship: number | null;
  ship_in_past: boolean;
  edited: string[];
}

export interface IntakePage { page: number; lines: string[]; }

export interface IntakeDocument {
  filename: string; mime: string; parser: string; pages: number; chars: number;
  size: number; needs_ocr: boolean; error: string; has_pdf: boolean;
}

export interface IntakeChain {
  id: number;
  live: boolean;
  runs: number[];
  opportunity: string;
  client_po: string;
  sales_order: string;
  customer: string;
  status: string;
  reply_count: number;
  ingested: Record<string, any>;
  subject: string;
  buyer_email: string;
  reply_to: string;
  reply_subject: string;
  timeline_count: number;
}

export interface ChainMail {
  dir: "in" | "out";
  id: number;
  at: string;
  from: string;
  to: string;
  subject: string;
  body: string;
  attachments: { filename?: string; size?: number; mime?: string }[];
  run_id?: number | null;
  route?: string;
  status?: string;
  message_id?: string;
}

export interface IntakeDetail extends IntakeRun {
  facts: any;
  matches: any;
  plan: IntakeStep[];
  chain?: IntakeChain | null;
  dates: IntakeDates;
  pages: IntakePage[];
  document: IntakeDocument;
  mail: { id?: number | null; subject: string; from_name: string; from_addr: string; received_at: string; body_text: string };
  attachments: {
    id: number; filename: string; mime: string; size: number; parser: string; pages: number;
    chars: number; ok: number; needs_ocr: number; error?: string; text_preview: string;
  }[];
  ack: { subject: string; body: string; grounding: { ok: boolean; unsourced: string[] } };
  edits: { id: number; field: string; original: string; corrected: string; actor?: string }[];
}

export interface IntakeThreadDoc extends IntakeRun {
  run_id: number;
  document: string;
  blocked: number;
  ready: number;
  chain_id?: number | null;
}

/* One card per MAIL THREAD: a conversation, with its documents as lines.
   A single reply carrying 3 POs + 3 BOMs used to be six cards for one conversation. */
export interface IntakeThread {
  key: string;
  chain_id?: number | null;
  subject: string;
  buyer: string;
  email: string;
  mails: number;
  first_at: string;
  last_at: string;
  documents: IntakeThreadDoc[];
  counts: {
    documents: number;
    waiting: number;
    approved: number;
    rejected: number;
    blocked_steps: number;
  };
}

export interface IntakeSummary {
  ui_hits?: number;
  total: number;
  understood: number;
  approved: number;
  rejected: number;
  blocked: number;
  simulated: number;
  ready_to_approve: number;
  live?: boolean;
}

export const ROUTE_LABEL: Record<string, string> = {
  new_order: "New purchase order",
  revision: "PO revision",
  enquiry: "Enquiry / RFQ",
  chain_reply: "Reply in a live thread",
  finance: "Invoice or remittance",
  other: "General mail",
};
