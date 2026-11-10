"""Cortex TnA Calendar — configuration constants.

Single source of truth. Business modules import from here and never read os.environ directly.
Identity/URL values are injected by the middleware at request time.
"""

import os as _os

PROJECT_SLUG = "cortex_tna_calendar"

# ── Identity (injected at runtime) ────────────────────────────────────────────
AGENT_ID      = _os.environ.get("AGENT_ID")      or ""
DEPLOYMENT_ID = _os.environ.get("DEPLOYMENT_ID") or ""
USER_ID       = _os.environ.get("USER_ID")       or ""
SWARM_ID      = _os.environ.get("SWARM_ID")      or ""
USER_JWT_TOKEN = _os.environ.get("USER_JWT_TOKEN") or ""

# ── KOGO URLs (from env only) ─────────────────────────────────────────────────
KOGO_API_BASE = _os.environ.get("KOGO_API_BASE") or ""
API_PATH      = _os.environ.get("API_PATH")      or ""
TOOL_URL      = _os.environ.get("TOOL_URL")      or ""
CHAT_API_PATH = _os.environ.get("CHAT_API_PATH") or ""

# ── Integration constants (env-overridable; defaults = current production) ────
ERP_APP_ID    = _os.environ.get("ERP_APP_ID")    or "6a84626b933cd6f2680eedac"
ERP_WRITE_MODE = (_os.environ.get("ERP_WRITE_MODE") or "draft").strip().lower()

# ── Cross-app bridge (Cortex Tower) ──────────────────────────────────────────
# The TnA Calendar and the Cortex Operations Control Tower are two separate KOGO
# apps. The TnA backend reaches the Tower through the KOGO middleware using the
# same injected API base + user token it already uses for the ERP gateway.
TOWER_PROJECT = _os.environ.get("TNA_TOWER_PROJECT") or "cortex_operations_control_tower"
# Optional: the deployed URL of the Cortex Tower app so TnA can jump to it.
# If empty, the URL can be saved from inside the app (local setting).
TOWER_APP_URL = _os.environ.get("TNA_TOWER_APP_URL") or ""

DEFAULT_CALENDAR = _os.environ.get("TNA_CALENDAR") or "VN_FACTORY"
DEFAULT_PRODUCT_TYPE = _os.environ.get("TNA_PRODUCT_TYPE") or "TPL-WOVEN-SHIRT-WASH"
# No order is assumed. When a caller sends no order_id the adapter reads the FIRST
# submitted Sales Order from the ERP (see erp.fetch_order). There is deliberately no
# default sample order: a stale name would show a calendar for an order that does not
# exist in the ERP.
TEST_ORDER_ID = _os.environ.get("TNA_TEST_ORDER") or ""

# ── Bundled data files (backend/data/) ────────────────────────────────────────
TEMPLATE_FILE = _os.environ.get("TNA_TEMPLATE_FILE") or "tna_template_woven_shirt.json"
HOLIDAYS_FILE = _os.environ.get("TNA_HOLIDAYS_FILE") or "holidays_2026.json"
SNAPSHOT_FILE = _os.environ.get("TNA_SNAPSHOT_FILE") or "tna_test_snapshot.json"

# ── Live-ERP read tuning ──────────────────────────────────────────────────────
GATEWAY_TIMEOUT = int(_os.environ.get("TNA_GATEWAY_TIMEOUT") or 40)
ERP_TIMEOUT     = int(_os.environ.get("TNA_ERP_TIMEOUT") or 40)
DATA_TTL        = int(_os.environ.get("TNA_DATA_TTL") or 60)     # in-process GET cache (s)
STATUS_TTL      = int(_os.environ.get("TNA_STATUS_TTL") or 15)   # connectivity probe cache (s)

# Serving company used to scope the Sales Order list (name, env-overridable).
ORDER_COMPANY = _os.environ.get("TNA_ORDER_COMPANY") or "CORTEX FASHION (HK) LIMITED"

# Force the bundled snapshot even when the ERP is reachable (deterministic QA / offline demos).
TNA_OFFLINE = (_os.environ.get("TNA_OFFLINE") or "").strip().lower() in ("1", "true", "yes", "on")

# While the ERP holds no Sales Order, show the bundled order marked "SAMPLE" (2026-11-07). 0 = empty page.
TNA_SAMPLE_WHEN_EMPTY = (_os.environ.get("TNA_SAMPLE_WHEN_EMPTY") or "0").strip() == "1"   # 2026-11-09: off by default (TNA plan G25); set 1 only for a demo

# ── Engine constants (data-driven; not hardcoded in logic) ────────────────────
# Closed status vocabulary (SPEC §8.1).
STATUS_VOCAB = [
    "Not started", "In progress", "Waiting for approval", "Waiting for material",
    "Completed", "Completed late", "At risk", "Blocked", "Overdue", "Not recorded",
]

# Milestones that legitimately have no recorded evidence show `Not recorded` (not `Overdue`).
NOT_RECORDED_CODES = ["SHIP", "DELIVERY"]

# Which ERP document is authoritative for `ORD_CONF`.
#   "client_po" (default) = Client Purchase Order.po_date  (the commercial gate)
#   "pde"                 = Production Daily Evidence.order_received_date (factory record)
ORDER_RECEIVED_SOURCE = (_os.environ.get("TNA_ORDER_RECEIVED_SOURCE") or "client_po").strip().lower()

# Milestone codes whose actuals the ERP adapter derives.
# 2026-10-07: extended from 11 to the full set of milestone codes that have an
# ERP evidence doctype (SPEC §11.2 / §14). Codes with no document present simply
# do not appear in `actuals` — they are never invented.
ERP_ACTUAL_CODES = [
    # Order / development
    "ORD_CONF", "SALES_CONTRACT", "TECH_PACK",
    # Material
    "FABRIC_PO", "FABRIC_INHOUSE", "FABRIC_INSPECT",
    "TRIMS_INHOUSE", "TRIMS_INSPECT",
    # Production
    "CUT_START", "CUT_END", "SEW_START", "SEW_END",
    "WASH_SEND", "WASH_RECV", "PACK_START", "PACK_END",
    # Quality / logistics
    "QC_INLINE", "QC_ENDLINE", "FINAL_INSP", "FORWARDER",
    "SHIP", "DELIVERY",
]

# Milestone codes that are auto-fed from the ERP when a document exists.
# (Superset of ERP_ACTUAL_CODES for documentation/UI; kept in sync above.)
ERP_EVIDENCE_DOCTYPES = {
    "ORD_CONF": "Client Purchase Order",
    "SALES_CONTRACT": "Sales Contract Evidence",
    "TECH_PACK": "Buyer Tech Sheet Evidence",
    "FABRIC_PO": "Purchase Order",
    "FABRIC_INHOUSE": "Purchase Receipt",
    "FABRIC_INSPECT": "Fabric Quality Evidence / Quality Inspection",
    "TRIMS_INHOUSE": "Purchase Receipt",
    "TRIMS_INSPECT": "Quality Inspection",
    "QC_INLINE": "Quality Inspection",
    "QC_ENDLINE": "Quality Inspection",
    "FINAL_INSP": "Quality Inspection",
    "FORWARDER": "Shipment Document Evidence",
    "SHIP": "Delivery Note / Garment Shipment Evidence",
    "DELIVERY": "Delivery Note",
}

# Default calendar per milestone category (data-driven; overridden by the
# template's per-milestone `calendar` field when present).
CATEGORY_CALENDAR = {
    "Material": "CN_FACTORY",
    "Logistics": "HK_OFFICE",
}

# ── Alerts / escalation (2026-10-07) ──────────────────────────────────────────
# Working days a milestone is open past its planned finish → escalation level.
ESCALATION_L1_WD = int(_os.environ.get("TNA_ESC_L1_WD") or 3)    # ≤ L1 → owner
ESCALATION_L2_WD = int(_os.environ.get("TNA_ESC_L2_WD") or 10)   # ≤ L2 → manager, else L3
ESCALATION_TARGETS = {1: "Owner", 2: "Department manager", 3: "Merchandising Manager / Director"}

# Multi-order program view default horizon (working days ahead).
PROGRAM_HORIZON_WD = int(_os.environ.get("TNA_PROGRAM_HORIZON_WD") or 120)

# `At risk` window — working days before the planned finish (SPEC §8.2 step 5.d).
AT_RISK_WINDOW_WD = int(_os.environ.get("TNA_AT_RISK_WD") or 3)

# Standard delay-cause list offered in the update form (SPEC §8.6).
DELAY_CAUSES = [
    "Late buyer comments", "Late sample approval", "Fabric mill delay",
    "Trim supplier delay", "Material quality failure", "Shade/shrinkage problem",
    "Capacity shortage", "Machine breakdown", "Labour shortage", "Rework",
    "Failed inspection", "Weather/transport", "Documentation", "Vessel/forwarder delay",
]

# Sentinel that clears a text/date field in the overlay (SPEC §6.6).
CLEAR_SENTINEL = "__clear__"

# Overlay write-path mode gate: off | safe | draft | all (SPEC §12).
WRITE_MODE_ORDER = {"off": 0, "safe": 1, "draft": 2, "all": 3}
