"""Cortex TnA Calendar — live KOGO ERP (Frappe / KOGO_SAS) read adapter.

Reads the client's ERP **live**, GET-only, to derive the TnA plan. Nothing here
ever writes to the ERP (writes live in ``writes.py`` and touch only the local
overlay).

Discovery (identical to the Cortex Control Tower, SPEC §11.1)::

    POST {API_PATH}[ /gateway]   Authorization: Bearer {USER_JWT_TOKEN}
      → getWorkspaceInstalledApps → pick app_type == "KOGO_SAS" (ERP_APP_ID hint)
      → getKogoSasApiKeys(app_id, workspace_id) → { api_base, api_key, api_secret }
    GET {api_base}/api/resource/<DocType>?filters=…&fields=…   (token auth)

Credentials are cached **in-process only** — never printed, logged, returned to
the frontend, or written to disk (SPEC §11.1 / NFR-9).

Data provenance rule: **every order comes from the ERP.** There is no automatic
demo/sample fallback. When the ERP has no orders, or the name asked for is not in
the ERP, the adapter says so (``source: "live"`` + ``no_orders`` / ``not_in_erp``)
instead of substituting bundled sample data. The bundled snapshot is read only when
``TNA_OFFLINE=1`` or ``force_snapshot`` is passed explicitly (deterministic tests).
The response carries ``source: "live" | "unavailable" | "snapshot"``.

Every helper swallows errors — nothing here raises.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

from . import config
DATA_DIR = Path(__file__).resolve().parent / "data"
SNAPSHOT_PATH = DATA_DIR / config.SNAPSHOT_FILE

# ── GraphQL discovery queries (fixed contract, copied verbatim) ───────────────
_APPS_QUERY = (
    "query($w:ID!){ getWorkspaceInstalledApps(workspace_id:$w)"
    "{ _id app_id app_type name category } }"
)
_KEYS_QUERY = (
    "query($a:String!,$w:ID!){ getKogoSasApiKeys(app_id:$a, workspace_id:$w)"
    "{ api_base api_key api_secret } }"
)

# In-process caches (never persisted).
_creds: Optional[dict] = None
_last_error: Optional[str] = None
_status_cache: Optional[tuple] = None
_data_cache: dict = {}
# Extended-evidence cache keyed by (style, po) so a program-wide sweep over many
# orders pays the doctype scan once, not once per order.
_evidence_cache: dict = {}

# Snapshot cache (bundled file never changes at runtime).
_snapshot_cache: Optional[dict] = None

# Daily-evidence quantity column → grouped milestone evidence.
_GROUP_FIELDS = {
    "cutting": "cutting_qty",
    "sewing": "sewing_qty",
    "sent_wash": "sent_wash_qty",
    "received_wash": "received_wash_qty",
    "packing": "packed_qty",
}
_FIELD_TO_CODE = {
    "cutting_qty": "CUT_START",
    "sewing_qty": "SEW_START",
    "sent_wash_qty": "WASH_SEND",
    "received_wash_qty": "WASH_RECV",
    "packed_qty": "PACK_START",
}


# ────────────────────────────────────────────────────────────────────────────
# Internal plumbing
# ────────────────────────────────────────────────────────────────────────────

def _set_error(err: Any) -> None:
    global _last_error
    try:
        _last_error = (str(err) or type(err).__name__)[:300]
    except Exception:
        _last_error = "unknown_error"


def last_error() -> Optional[str]:
    """The most recent swallowed error (human-readable).

    Used to populate ``warnings[]`` — never contains a credential."""
    return _last_error


def _gateway(query: str, variables: dict) -> dict:
    url = config.API_PATH or ""
    if url and not url.endswith("/gateway"):
        url += "/gateway"
    r = requests.post(
        url,
        json={"query": query, "variables": variables},
        headers={
            "Authorization": f"Bearer {config.USER_JWT_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=config.GATEWAY_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("data") or {}


def _discover() -> dict:
    """Ask the KOGO gateway for this workspace's KOGO ERP API keys.

    Returns ``{"BASE": ..., "AUTH": {...}}`` or ``{}``. Never raises."""
    ws = config.SWARM_ID or config.AGENT_ID
    app_id = config.ERP_APP_ID
    try:
        data = _gateway(_APPS_QUERY, {"w": ws})
        apps = data.get("getWorkspaceInstalledApps") or []
        sas = [a for a in apps if str(a.get("app_type") or "") == "KOGO_SAS"]
        if sas:
            chosen = next((a for a in sas if a.get("app_id") == config.ERP_APP_ID), sas[0])
            if chosen.get("app_id"):
                app_id = chosen["app_id"]
    except Exception as e:
        _set_error(e)
    try:
        data = _gateway(_KEYS_QUERY, {"a": app_id, "w": ws})
    except Exception as e:
        _set_error(e)
        return {}
    k = data.get("getKogoSasApiKeys") or {}
    base = (k.get("api_base") or "").rstrip("/")
    key = k.get("api_key")
    secret = k.get("api_secret")
    if not base or not key or not secret:
        _set_error("erp_keys_incomplete")
        return {}
    return {"BASE": base, "AUTH": {"Authorization": f"token {key}:{secret}"}}


def get_creds() -> dict:
    """Return cached ERP creds, discovering them once when missing. Never raises.

    The credential dict is intentionally module-private in effect — it is never
    logged or included in any response."""
    global _creds
    if _creds:
        return _creds
    _creds = _discover()
    return _creds


def _rediscover() -> dict:
    global _creds, _status_cache
    _creds = None
    _status_cache = None
    return get_creds()


def _cache_get(key):
    hit = _data_cache.get(key)
    if hit and (time.time() - hit[0]) < config.DATA_TTL:
        return True, hit[1]
    return False, None


def _cache_put(key, value) -> None:
    _data_cache[key] = (time.time(), value)


def erp_invalidate_cache() -> None:
    """Drop the in-process read cache."""
    _data_cache.clear()
    _evidence_cache.clear()


def _base_key() -> str:
    return ((get_creds() or {}).get("BASE") or "")


def _request(path: str, params: Optional[dict] = None, retry: bool = True):
    """GET ``<base><path>``. Returns ``(ok, payload)``. Never raises."""
    creds = get_creds()
    base = (creds or {}).get("BASE") or ""
    headers = (creds or {}).get("AUTH") or {}
    if not base:
        _set_error(_last_error or "no_erp_credentials")
        return False, None
    try:
        r = requests.get(base + path, headers=headers, params=params or {}, timeout=config.ERP_TIMEOUT)
        if r.status_code in (401, 403) and retry:
            _set_error(f"erp_auth_failed_{r.status_code}")
            if _rediscover():
                return _request(path, params, retry=False)
            return False, None
        if r.status_code >= 400:
            _set_error(f"erp_http_{r.status_code}")
            return False, None
        payload = r.json()
        if isinstance(payload, dict) and payload.get("exc"):
            _set_error(payload.get("exc_type") or "erp_exception")
            return False, None
        return True, payload
    except Exception as e:
        _set_error(e)
        return False, None


# ────────────────────────────────────────────────────────────────────────────
# Public read helpers — all GET, all error-swallowing
# ────────────────────────────────────────────────────────────────────────────

def erp_get(doctype: str, fields=None, filters=None, limit: int = 500, order=None) -> list:
    """List documents from ``doctype``. Returns ``[]`` on any failure. Never raises."""
    doctype = str(doctype)
    path = f"/api/resource/{quote(doctype)}"
    params: dict = {"limit_page_length": int(limit or 0)}
    if fields is not None:
        params["fields"] = json.dumps(fields)
    if filters is not None:
        params["filters"] = json.dumps(filters)
    if order:
        params["order_by"] = order
    key = ("get", _base_key(), doctype, json.dumps(fields), json.dumps(filters), limit, order)
    cached, val = _cache_get(key)
    if cached:
        return val
    ok, payload = _request(path, params)
    if not ok:
        return []
    data = (payload or {}).get("data")
    rows = data if isinstance(data, list) else []
    _cache_put(key, rows)
    return rows


def erp_doc(doctype: str, name: str) -> dict:
    """Fetch a single full document (needed for child tables such as ``items``).
    Returns ``{}`` on any failure. Never raises."""
    path = f"/api/resource/{quote(str(doctype))}/{quote(str(name))}"
    key = ("doc", _base_key(), str(doctype), str(name))
    cached, val = _cache_get(key)
    if cached:
        return val
    ok, payload = _request(path)
    if not ok:
        return {}
    data = (payload or {}).get("data")
    if not isinstance(data, dict):
        return {}
    _cache_put(key, data)
    return data


def erp_status() -> dict:
    """``{"connected": bool, "error": str|None}`` — cached briefly.

    Note: deliberately does **not** expose the ERP base URL or any credential."""
    global _status_cache
    try:
        now = time.time()
        if _status_cache and (now - _status_cache[0]) < config.STATUS_TTL:
            return _status_cache[1]
        connected = False
        error: Optional[str] = None
        if (get_creds() or {}).get("BASE"):
            ok, _payload = _request("/api/method/frappe.ping")
            connected = bool(ok)
            if not connected:
                error = _last_error or "erp_unreachable"
        else:
            error = _last_error or "no_erp_credentials"
        status = {"connected": connected, "error": None if connected else (error or "erp_unavailable")}
        _status_cache = (now, status)
        return status
    except Exception as e:
        _set_error(e)
        return {"connected": False, "error": "erp_unavailable"}


def erp_available() -> bool:
    """True when the ERP answers. Never raises."""
    if config.TNA_OFFLINE:
        return False
    try:
        return bool(erp_status().get("connected"))
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────────────
# Snapshot fallback
# ────────────────────────────────────────────────────────────────────────────

def load_snapshot() -> dict:
    """Load (and cache in-process) the bundled snapshot. Never raises."""
    global _snapshot_cache
    if _snapshot_cache is not None:
        return _snapshot_cache
    try:
        _snapshot_cache = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        _set_error(e)
        _snapshot_cache = {}
    return _snapshot_cache


# ────────────────────────────────────────────────────────────────────────────
# Actual derivation (identical for live PDE rows and snapshot daily_entries)
# ────────────────────────────────────────────────────────────────────────────

def _pcs(v) -> str:
    try:
        return f"{int(round(float(v))):,}"
    except Exception:
        return "0"


def _derive_actuals(daily: list, order_received: Optional[str],
                    ship_date: Optional[str], shipped_date: Optional[str]):
    """Derive the 11 ERP-actual milestone dates from daily production evidence.

    Rule (SPEC §11.2): ``actual_start = MIN(production_date where qty > 0)``,
    ``actual_finish = MAX(...)``. A row dated **after the ship date** is
    chronologically inconsistent and is excluded (preserved under
    ``data_quality`` — never silently corrected).

    Returns ``(actuals_by_code, excluded_rows)``.
    """
    kept: list = []
    excluded: list = []
    for e in daily or []:
        d = str(e.get("production_date") or "")[:10]
        if not d:
            continue
        if ship_date and d > ship_date:
            excluded.append(e)
            continue
        kept.append((d, e))
    kept.sort(key=lambda t: t[0])

    groups: dict = {}
    for name, field in _GROUP_FIELDS.items():
        rows = [(d, float(e.get(field) or 0)) for d, e in kept if float(e.get(field) or 0) > 0]
        if not rows:
            continue
        groups[name] = {
            "start": rows[0][0],
            "end": rows[-1][0],
            "total": sum(q for _, q in rows),
            "first_qty": rows[0][1],
            "last_qty": rows[-1][1],
        }

    out: dict = {}
    if order_received:
        out["ORD_CONF"] = {"start": order_received, "finish": order_received,
                           "evidence_value": order_received, "retrieved": True,
                           "source_doctype": "Production Daily Evidence"}

    plan = [
        ("CUT_START", "cutting", "start"),
        ("CUT_END", "cutting", "end"),
        ("SEW_START", "sewing", "start"),
        ("SEW_END", "sewing", "end"),
        ("WASH_SEND", "sent_wash", "span"),
        ("WASH_RECV", "received_wash", "span"),
        ("PACK_START", "packing", "start"),
        ("PACK_END", "packing", "end"),
    ]
    for code, gname, mode in plan:
        g = groups.get(gname)
        if not g:
            continue
        if mode == "start":
            s = f = g["start"]
            ev = f"{g['start']} ({_pcs(g['first_qty'])} pcs)"
        elif mode == "end":
            s, f = g["start"], g["end"]
            ev = (f"{g['start']} ({_pcs(g['first_qty'])} pcs)" if g["start"] == g["end"]
                  else f"{g['start']} → {g['end']} ({_pcs(g['total'])} pcs)")
        else:  # span
            s, f = g["start"], g["end"]
            ev = (f"{g['start']} → {g['end']} ({_pcs(g['total'])} pcs)" if g["start"] != g["end"]
                  else f"{g['start']} ({_pcs(g['total'])} pcs)")
        out[code] = {"start": s, "finish": f, "evidence_value": ev,
                     "retrieved": True, "source_doctype": "Production Daily Evidence",
                     "qty": g["total"]}

    if shipped_date:
        for code in ("SHIP", "DELIVERY"):
            out[code] = {"start": shipped_date, "finish": shipped_date,
                         "evidence_value": shipped_date, "retrieved": True,
                         "source_doctype": "Delivery Note"}
    return out, excluded


# ────────────────────────────────────────────────────────────────────────────
# Extended evidence → milestone actuals (added 2026-10-07)
#
# The first build only derived the 8 production activities from Production Daily
# Evidence. Six further milestones have real evidence sitting in other ERP
# doctypes and are now read live. Never invented: a code only appears when its
# document exists for this style/order.
# ────────────────────────────────────────────────────────────────────────────

def _act(start, finish, evidence, doctype: str, **extra) -> dict:
    d = {"start": start, "finish": finish, "evidence_value": evidence,
         "retrieved": True, "source_doctype": doctype}
    d.update(extra)
    return d


def _style_fabric_code(style_no: Optional[str]) -> Optional[str]:
    """``C2027-S84-304`` → ``S84`` (the fabric/quality code embedded in the style)."""
    parts = str(style_no or "").split("-")
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return None


def _fabric_item_match(item_code: Any, fabric_code: Optional[str]) -> bool:
    ic = str(item_code or "").upper()
    return bool(fabric_code) and ic.startswith("FAB-") and (str(fabric_code).upper() in ic)


def _fetch_docs_parallel(doctype: str, names: list, workers: int = 12) -> list:
    """Fetch many full documents concurrently (child tables require full docs).
    Order is preserved; failures are dropped. Never raises."""
    names = [n for n in (names or []) if n]
    if not names:
        return []
    out: list = []
    try:
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
            for doc in ex.map(lambda n: erp_doc(doctype, n), names):
                if doc:
                    out.append(doc)
    except Exception as e:
        _set_error(e)
    return out


# ── Global evidence index (built once per TTL across ALL styles) ────────────
# The first build re-fetched every evidence doctype for every style. This builds
# one in-memory index so a program sweep over N orders costs one scan, not N.

_evidence_index_cache: Optional[tuple] = None


def _safe_list(doctype: str, fields: list, filters=None, limit: int = 500) -> list:
    """``erp_get`` that treats a doctype this ERP does not have as "no evidence", silently."""
    try:
        return erp_get(doctype, fields=fields, filters=filters, limit=limit) or []
    except Exception:
        return []


def _styles_in(text: Any) -> list:
    """``"HL-1001, HL-1002\nHL-1003"`` → the style numbers (Small Text fields list several)."""
    return [t.strip() for t in re.split(r"[,;\n/]+", str(text or "")) if t.strip()]


def _evidence_index() -> dict:
    """Build (and cache) a style / PO → date index over the ERP's evidence records.

    2026-11-07: repointed to the Arinox doctypes this ERP actually has (Sales Contract, Tech Pack,
    Sample Approval, PP Meeting, Fabric/Trim/Final Inspection, Cut Plan, Packing List). The older
    "… Evidence" doctypes of the CORTEX set do not exist here; reading them returned nothing and
    left the calendar without a single actual date.
    """
    global _evidence_index_cache
    if _evidence_index_cache and (time.time() - _evidence_index_cache[0]) < config.DATA_TTL:
        return _evidence_index_cache[1]

    idx: dict = {
        "contracts": {}, "techpacks": {}, "cpos": {},
        "fabric_po": {}, "fabric_recv": {}, "fabric_test": {},
        "fabric_qi": {}, "inspection": [], "ship": {},
        "samples": {}, "pp_meeting": {}, "trim_inspect": {}, "marker": {}, "final": {}, "packlist": {},
    }

    def _put(d, k, v):
        if k and v and k not in d:
            d[k] = v

    def _fab_code(item_code):
        parts = str(item_code or "").upper().split("-")
        return parts[1] if len(parts) >= 2 and parts[0] == "FAB" else None

    # Sales Contract — child items carry style_no; the header carries contract_date.
    rows = _safe_list("Sales Contract", ["name", "contract_date", "docstatus"], limit=300)
    for doc in _fetch_docs_parallel("Sales Contract", [r.get("name") for r in rows if int(r.get("docstatus") or 0) != 2]):
        d0 = doc.get("contract_date")
        for it in doc.get("items") or []:
            _put(idx["contracts"], it.get("style_no"), d0)

    # Tech Pack — style_no → received_on.
    for r in _safe_list("Tech Pack", ["name", "style_no", "received_on", "docstatus"]):
        if int(r.get("docstatus") or 0) != 2:
            _put(idx["techpacks"], r.get("style_no"), r.get("received_on"))

    # Sample Approval — style_no → {sample type: approved/submitted date}.
    for r in _safe_list("Sample Approval", ["name", "style_no", "sample_type", "status", "submitted_on", "approved_on"]):
        st = idx["samples"].setdefault(r.get("style_no") or "", {})
        kind = str(r.get("sample_type") or "").lower()
        _put(st, kind + ":sub", r.get("submitted_on"))
        _put(st, kind + ":app", r.get("approved_on"))

    # PP Meeting — style_no → meeting_date (held).
    for r in _safe_list("PP Meeting", ["name", "style_no", "meeting_date", "status"]):
        _put(idx["pp_meeting"], r.get("style_no"), r.get("meeting_date"))

    # Fabric / Trim Inspection — style_nos (a list in one field) → date.
    for r in _safe_list("Fabric Inspection", ["name", "style_nos", "inspection_date", "docstatus"]):
        for sn in _styles_in(r.get("style_nos")):
            _put(idx["fabric_test"], sn, r.get("inspection_date"))
    for r in _safe_list("Trim Inspection", ["name", "style_nos", "received_date", "docstatus"]):
        for sn in _styles_in(r.get("style_nos")):
            _put(idx["trim_inspect"], sn, r.get("received_date"))

    # Cut Plan approved → marker approved.
    for r in _safe_list("Cut Plan", ["name", "style_no", "approved_on", "status"]):
        if r.get("approved_on"):
            _put(idx["marker"], r.get("style_no"), str(r.get("approved_on"))[:10])

    # Final Inspection / Packing List — keyed by the style item (an Item code).
    for r in _safe_list("Final Inspection", ["name", "style_item", "inspection_date", "docstatus"]):
        _put(idx["final"], r.get("style_item"), r.get("inspection_date"))
    for r in _safe_list("Packing List", ["name", "style_item", "packing_date", "docstatus"]):
        _put(idx["packlist"], r.get("style_item"), {"date": r.get("packing_date"), "name": r.get("name")})

    # Client Purchase Orders (older ERP sets only) — po_no → po_date.
    for r in _safe_list("Client Purchase Order", ["name", "client_po_no", "po_date"]):
        _put(idx["cpos"], r.get("client_po_no"), r.get("po_date"))

    # Purchase Orders → fabric_code → transaction_date.
    rows = _safe_list("Purchase Order", ["name", "transaction_date", "docstatus"])
    for doc in _fetch_docs_parallel("Purchase Order", [r.get("name") for r in rows if int(r.get("docstatus") or 0) == 1]):
        d0 = doc.get("transaction_date")
        for it in doc.get("items") or []:
            _put(idx["fabric_po"], _fab_code(it.get("item_code")), d0)

    # Purchase Receipts → fabric_code → posting_date.
    rows = _safe_list("Purchase Receipt", ["name", "posting_date", "docstatus"])
    for doc in _fetch_docs_parallel("Purchase Receipt", [r.get("name") for r in rows if int(r.get("docstatus") or 0) == 1]):
        d0 = doc.get("posting_date")
        for it in doc.get("items") or []:
            _put(idx["fabric_recv"], _fab_code(it.get("item_code")), d0)

    # Quality Inspection → fabric_code map + full inspection list.
    for r in _safe_list("Quality Inspection", ["name", "report_date", "item_code", "inspection_type", "status"]):
        ic = str(r.get("item_code") or "")
        _put(idx["fabric_qi"], _fab_code(ic), r.get("report_date"))
        idx["inspection"].append({
            "item_code": ic, "date": r.get("report_date"),
            "type": str(r.get("inspection_type") or "").strip().lower(),
            "status": r.get("status"),
        })

    _evidence_index_cache = (time.time(), idx)
    return idx


def _by_item(index: dict, style: str):
    """First entry whose Item code is this style or one of its SKUs (``HL-1001`` / ``HL-1001-M``)."""
    if style in index:
        return index[style]
    for k, v in index.items():
        if k and (str(k).startswith(style + "-") or style.startswith(str(k))):
            return v
    return None


def _live_evidence_actuals(style_no: Optional[str], po_no: Optional[str],
                           order_received: Optional[str]) -> dict:
    """Derive milestone actuals for one style from the global evidence index.

    A code only appears when its document exists in the ERP — never invented.
    """
    out: dict = {}
    style = str(style_no or "")
    if not style:
        return out
    fabric = _style_fabric_code(style)
    idx = _evidence_index()

    d0 = idx["contracts"].get(style)
    if d0:
        out["SALES_CONTRACT"] = _act(d0, d0, d0, "Sales Contract")

    d0 = idx["techpacks"].get(style)
    if d0:
        out["TECH_PACK"] = _act(d0, d0, d0, "Tech Pack")

    smp = idx["samples"].get(style) or {}
    for kind, code_sub, code_app in (("proto", "PROTO_SAMPLE", "PROTO_APPROVE"), ("fit", None, "FIT_APPROVE"),
                                     ("size", None, "SIZE_SET"), ("pp", "PP_SAMPLE_SUB", "PP_SAMPLE_APP"),
                                     ("lab", "LABDIP_SUB", "LABDIP_APP")):
        for k, v in smp.items():
            if kind in k.split(":")[0]:
                if code_sub and k.endswith(":sub") and v:
                    out.setdefault(code_sub, _act(v, v, v, "Sample Approval"))
                if code_app and k.endswith(":app") and v:
                    out.setdefault(code_app, _act(v, v, v, "Sample Approval"))

    d0 = idx["pp_meeting"].get(style)
    if d0:
        out["PP_MEETING"] = _act(d0, d0, d0, "PP Meeting")

    d0 = idx["marker"].get(style)
    if d0:
        out["MARKER_APP"] = _act(d0, d0, d0, "Cut Plan")

    d0 = idx["trim_inspect"].get(style)
    if d0:
        out["TRIMS_INSPECT"] = _act(d0, d0, d0, "Trim Inspection")

    if po_no:
        d0 = idx["cpos"].get(str(po_no))
        if d0:
            out["ORD_CONF"] = _act(d0, d0, f"PO {po_no} · {d0}", "Client Purchase Order")

    if fabric:
        d0 = idx["fabric_po"].get(fabric)
        if d0:
            out["FABRIC_PO"] = _act(d0, d0, d0, "Purchase Order")
        d0 = idx["fabric_recv"].get(fabric)
        if d0:
            out["FABRIC_INHOUSE"] = _act(d0, d0, d0, "Purchase Receipt")

    d0 = idx["fabric_test"].get(style)
    if d0:
        out["FABRIC_INSPECT"] = _act(d0, d0, d0, "Fabric Inspection")
    elif fabric:
        d0 = idx["fabric_qi"].get(fabric)
        if d0:
            out["FABRIC_INSPECT"] = _act(d0, d0, d0, "Quality Inspection")

    d0 = _by_item(idx["final"], style)
    if d0:
        out["FINAL_INSP"] = _act(d0, d0, d0, "Final Inspection")

    # In-process / final inspection from ERPNext Quality Inspection, when present.
    for insp in idx["inspection"]:
        ic, d0, t = insp["item_code"], insp["date"], insp["type"]
        if not d0 or not (ic.startswith(style) or style.startswith(ic)):
            continue
        ev = f"{d0} ({insp['status'] or ''})".strip()
        if t in ("final", "pre delivery", "pre-delivery", "outgoing"):
            out.setdefault("FINAL_INSP", _act(d0, d0, ev, "Quality Inspection"))
        elif t in ("in process", "in-process", "inline", "in line"):
            out.setdefault("QC_INLINE", _act(d0, d0, ev, "Quality Inspection"))

    pl = _by_item(idx["packlist"], style)
    if pl and pl.get("date"):
        d0 = pl["date"]
        out["PACKLIST"] = _act(d0, d0, f"packing list {pl.get('name')} · {d0}", "Packing List")

    return out


def _order_tna_actuals(sales_order: str) -> dict:
    """Actual dates the ERP's own TNA Milestone rows carry for this order (milestone_type = code)."""
    out: dict = {}
    if not sales_order:
        return out
    for r in _safe_list("TNA Milestone", ["name", "milestone_type", "label", "actual_date", "status"],
                        filters=[["sales_order", "=", sales_order]], limit=200):
        code = str(r.get("milestone_type") or "").strip().upper().replace(" ", "_")
        d0 = r.get("actual_date")
        if code and d0:
            out[code] = _act(d0, d0, f"{r.get('name')} · {d0}", "TNA Milestone")
    return out


def _live_evidence_actuals_cached(style_no: Optional[str], po_no: Optional[str],
                                  order_received: Optional[str]) -> dict:
    """``_live_evidence_actuals`` behind a short in-process TTL cache."""
    key = (str(style_no or ""), str(po_no or ""))
    hit = _evidence_cache.get(key)
    if hit and (time.time() - hit[0]) < config.DATA_TTL:
        return hit[1]
    val = _live_evidence_actuals(style_no, po_no, order_received)
    _evidence_cache[key] = (time.time(), val)
    return val


def _merge_evidence(actuals: dict, evidence: dict,
                    order_received: Optional[str]) -> dict:
    """Merge extended-evidence actuals into the PDE-derived actuals.

    * ``ORD_CONF`` honours ``config.ORDER_RECEIVED_SOURCE`` (client PO vs PDE).
    * ``SHIP`` / ``DELIVERY`` already set from a submitted Delivery Note are kept
      (the Delivery Note is authoritative over Garment Shipment Evidence).
    """
    evidence = dict(evidence or {})
    if "ORD_CONF" in evidence:
        if config.ORDER_RECEIVED_SOURCE == "client_po":
            ev = evidence.pop("ORD_CONF")
            if order_received:
                ev["evidence_alt"] = f"factory order-received {order_received}"
            actuals["ORD_CONF"] = ev
        else:
            evidence.pop("ORD_CONF", None)
    for code, ev in evidence.items():
        if code in ("SHIP", "DELIVERY") and actuals.get(code):
            continue
        actuals[code] = ev
    return actuals


def _data_quality_from_excluded(excluded: list) -> list:
    """Build ``data_quality`` entries for rows excluded from the actuals."""
    out: list = []
    for e in excluded or []:
        d = str(e.get("production_date") or "")[:10]
        affected = None
        qty = None
        label = "qty"
        for field, code in _FIELD_TO_CODE.items():
            if float(e.get(field) or 0) > 0:
                affected = code
                qty = _pcs(e.get(field))
                label = _GROUP_FIELDS.get(next((g for g, f in _GROUP_FIELDS.items() if f == field), ""), field)
                break
        detail = f" ({label} {qty})" if qty else ""
        out.append({
            "issue": f"one daily row dated {d} is chronologically inconsistent{detail}",
            "erp_note": (f"Source date {d} is preserved verbatim; it is chronologically "
                         f"inconsistent with the surrounding production rows and requires source review."),
            "affected_code": affected,
        })
    return out


# ────────────────────────────────────────────────────────────────────────────
# Live order reads
# ────────────────────────────────────────────────────────────────────────────

def _parse_item(item: dict) -> dict:
    """Split an item_code like ``C2027-S84-304-MICTP-XS`` into style/colour/size."""
    code = str(item.get("item_code") or "")
    parts = code.split("-")
    if len(parts) >= 3:
        size = parts[-1]
        colour = parts[-2]
        style = "-".join(parts[:-2])
    else:
        size, colour, style = "", "", code
    name = str(item.get("item_name") or "")
    if " - " in name:
        name = name.split(" - ")[0]
    return {
        "style_no": style, "colour": colour, "size": size,
        "style_name": name, "qty": float(item.get("qty") or 0),
    }


def _order_from_items(so: dict, customer_legal: Optional[str], po_no: Optional[str],
                      site: Optional[str], source: str) -> dict:
    sizes: dict = {}
    style_no = colour = style_name = None
    for it in so.get("items") or []:
        p = _parse_item(it)
        if p["style_no"] and not style_no:
            style_no = p["style_no"]
        if p["colour"] and not colour:
            colour = p["colour"]
        if p["style_name"] and not style_name:
            style_name = p["style_name"]
        if p["size"]:
            sizes[p["size"]] = sizes.get(p["size"], 0) + p["qty"]
    qty = so.get("total_qty")
    if not qty:
        qty = sum(sizes.values()) if sizes else 0
    return {
        "sales_order": so.get("name"),
        "sales_order_status": so.get("status") or "",
        "docstatus": int(so.get("docstatus") or 0),
        "customer": so.get("customer") or so.get("customer_name") or "",
        "customer_legal": customer_legal,
        "company": so.get("company") or "",
        "po_no": po_no,
        "client_po_no": so.get("custom_client_po") or None,
        "po_date": so.get("transaction_date") or None,
        "delivery_date": so.get("delivery_date") or None,
        "qty": float(qty or 0),
        "grand_total": float(so.get("grand_total") or 0),
        "currency": so.get("currency") or "",
        "style_no": style_no,
        "style_name": style_name,
        "colour": colour,
        "sizes": sizes,
        "site": site,
        "product_type": config.DEFAULT_PRODUCT_TYPE,
        "template_id": config.DEFAULT_PRODUCT_TYPE,
        "_source": source,
    }


def _live_shipped(style_no: Optional[str], customer: Optional[str]):
    """Ship date from a **submitted Delivery Note** whose items carry this style.

    Garment Shipment Evidence is deliberately NOT used here: the packed figures
    for this order conflict and there are 0 Delivery Notes, so the correct
    rendering is ``Not recorded`` (SPEC §16.1 / AC-5). Never raises."""
    if not style_no:
        return None
    ck = ("shipped", str(style_no), str(customer or ""))
    hit = _data_cache.get(ck)
    if hit and (time.time() - hit[0]) < config.DATA_TTL:
        return hit[1]
    rows = erp_get(
        "Delivery Note",
        fields=["name", "posting_date", "customer", "docstatus"],
        filters=[["customer", "=", customer], ["docstatus", "=", 1]],
        limit=30,
    )
    result = None
    for doc in _fetch_docs_parallel("Delivery Note", [r.get("name") for r in rows]):
        for it in doc.get("items") or []:
            if str(it.get("item_code") or "").startswith(str(style_no)):
                result = doc.get("posting_date")
                break
        if result:
            break
    _data_cache[ck] = (time.time(), result)
    return result


def _live_order(order_id: str, light: bool = False):
    """Read one order live. Returns a normalized dict, or ``None`` when the ERP
    is unusable (caller then falls back to the snapshot). Never raises."""
    so = erp_doc("Sales Order", order_id)
    if not so:
        if erp_available():
            return {"error": f"Order '{order_id}' not found",
                    "available_orders": _live_order_ids(),
                    "source": "live"}
        return None

    style_no = None
    for it in so.get("items") or []:
        style_no = _parse_item(it)["style_no"] or style_no
        if style_no:
            break

    # Customer legal entity (real ERP value; never invented).
    customer_legal = None
    customer = so.get("customer") or so.get("customer_name")
    if customer:
        cust = erp_doc("Customer", customer)
        customer_legal = cust.get("custom_legal_entity") or None

    # PO number: the SO header `po_no` is blank in this ERP, so read the real
    # linked Buyer Tech Sheet Evidence PO (never a fabricated value).
    po_no = so.get("po_no") or None
    daily: list = []
    order_received = None
    site = None
    if style_no:
        for r in _safe_list("Production Daily Evidence", ["name", "style_no", "order_received_date"],
                            filters=[["style_no", "=", style_no]], limit=10):
            if r.get("order_received_date") and not order_received:
                order_received = r.get("order_received_date")
            doc = erp_doc("Production Daily Evidence", r.get("name"))
            if doc.get("site") and not site:
                site = doc.get("site")
            if doc.get("order_received_date") and not order_received:
                order_received = doc.get("order_received_date")
            for it in doc.get("items") or []:
                daily.append(it)
        if not po_no:
            btse = _safe_list("Buyer Tech Sheet Evidence", ["name", "style_no", "customer_po_no"],
                              filters=[["style_no", "=", style_no]], limit=1)
            if btse:
                po_no = btse[0].get("customer_po_no") or None

    if not order_received:
        order_received = so.get("transaction_date") or None       # the order's own date when no factory record says otherwise
    order = _order_from_items(so, customer_legal, po_no, site, "live")
    ship_date = order.get("delivery_date")
    shipped_date = None if light else _live_shipped(order.get("style_no"), customer)
    actuals, excluded = _derive_actuals(daily, order_received, ship_date, shipped_date)

    # Extended evidence wiring — contract, tech pack, fabric PO/receipt/inspection,
    # trims, quality inspection, forwarder docs and the shipment date. A code only
    # appears when its document exists for this style (never invented).
    evidence = _live_evidence_actuals_cached(order.get("style_no"), po_no, order_received)
    _merge_evidence(actuals, evidence, order_received)
    # the ERP's own T&A rows (Order TNA → TNA Milestone) are the system of record when they exist
    for code, ev in _order_tna_actuals(order.get("sales_order") or order_id).items():
        actuals[code] = ev

    warnings: list = []
    if not order.get("style_no"):
        warnings.append("The Sales Order has no item rows; style could not be derived.")

    return {
        "source": "live",
        "warnings": warnings,
        "order": order,
        "actuals": actuals,
        "data_quality": _data_quality_from_excluded(excluded),
    }


def _selling_company() -> str:
    """The company the order book is scoped to, discovered from the ERP.

    The configured name is used ONLY when the ERP actually has that company;
    otherwise the ERP's single company is used, and when there are several the
    filter is dropped ("") so real orders are never hidden by a stale constant.
    Cached for 10 minutes. Never raises."""
    ck = ("selling_company",)
    hit = _data_cache.get(ck)
    if hit and (time.time() - hit[0]) < 600:
        return hit[1]
    name = ""
    try:
        rows = erp_get("Company", fields=["name"], limit=20)
        names = [r.get("name") for r in rows if r.get("name")]
        want = (config.ORDER_COMPANY or "").strip()
        if want and want in names:
            name = want
        elif len(names) == 1:
            name = names[0]
    except Exception as e:
        _set_error(e)
    _data_cache[ck] = (time.time(), name)
    return name


def _live_order_ids() -> list:
    filt = [["docstatus", "<", 2]]       # drafts too: intake creates draft orders (2026-11-07)
    company = _selling_company()
    if company:
        filt.append(["company", "=", company])
    rows = erp_get("Sales Order", fields=["name"], filters=filt,
                   limit=200, order="name asc")
    return [r.get("name") for r in rows if r.get("name")]


# ────────────────────────────────────────────────────────────────────────────
# Snapshot order
# ────────────────────────────────────────────────────────────────────────────

def _snapshot_order(order_id: str):
    snap = load_snapshot()
    o = snap.get("order") or {}
    if o.get("sales_order") != order_id:
        return None
    act = snap.get("actuals") or {}
    order_received = act.get("order_received_date")
    shipped = act.get("shipped")
    ship_date = o.get("delivery_date")
    actuals, excluded = _derive_actuals(snap.get("daily_entries") or [], order_received, ship_date, shipped)
    # Extended evidence actuals (bundled so offline == live).
    _merge_evidence(actuals, snap.get("evidence_actuals") or {}, order_received)

    # data_quality — snapshot entries verbatim, enriched with the affected code.
    dq: list = []
    for item in snap.get("data_quality") or []:
        entry = dict(item)
        if "affected_code" not in entry:
            entry["affected_code"] = None
        for e in excluded:
            for field, code in _FIELD_TO_CODE.items():
                if float(e.get(field) or 0) > 0 and entry.get("affected_code") is None:
                    entry["affected_code"] = code
        dq.append(entry)
    if not dq and excluded:
        dq = _data_quality_from_excluded(excluded)

    order = dict(o)
    order["_source"] = "snapshot"
    order["product_type"] = config.DEFAULT_PRODUCT_TYPE
    order["template_id"] = config.DEFAULT_PRODUCT_TYPE
    order["client_po_no"] = order.get("client_po_no") or None
    return {
        "source": "snapshot",
        "warnings": [],
        "order": order,
        "actuals": actuals,
        "data_quality": dq,
    }


# ────────────────────────────────────────────────────────────────────────────
# Public entry points used by functions.py
# ────────────────────────────────────────────────────────────────────────────

def fetch_order(order_id: str = "", force_snapshot: bool = False, light: bool = False) -> dict:
    """Return the normalized order + derived actuals, read LIVE from the ERP.

    ``light=True`` skips the Delivery Note scan (the shipment date still comes from
    Garment Shipment Evidence via the shared evidence index) — used by the
    multi-order program sweep so it does not re-scan Delivery Notes per order.

    With no ``order_id`` the FIRST submitted Sales Order in the ERP is used. Nothing
    is ever invented: an ERP with no orders returns ``no_orders``, and a name the ERP
    does not hold returns ``not_in_erp``. The bundled snapshot is only read when
    ``TNA_OFFLINE=1`` or ``force_snapshot`` is passed. Never raises."""
    offline = bool(force_snapshot or config.TNA_OFFLINE)
    order_id = (str(order_id) if order_id else "").strip()

    if offline:
        snap = _snapshot_order(order_id or config.TEST_ORDER_ID)
        if snap is not None:
            return snap
        return {"error": f"Order '{order_id}' is not in the offline snapshot",
                "source": "snapshot", "not_in_erp": True,
                "available_orders": snapshot_order_ids()}

    if not erp_available():
        err = last_error() or "no answer"
        return {"error": "The ERP is not reachable, so no order can be read.",
                "source": "unavailable", "erp_unreachable": True,
                "available_orders": [],
                "warnings": [f"The ERP is unreachable ({err})."]}

    if not order_id:
        ids = _live_order_ids()
        if not ids:
            if config.TNA_SAMPLE_WHEN_EMPTY:
                sample = _sample_order()
                if sample:
                    return sample
            return {"error": "There are no sales orders in the ERP yet.",
                    "source": "live", "no_orders": True, "available_orders": []}
        order_id = ids[0]
    elif config.TNA_SAMPLE_WHEN_EMPTY and order_id in snapshot_order_ids() and not erp_doc("Sales Order", order_id):
        sample = _sample_order()
        if sample:
            return sample

    res = _live_order(order_id, light=light)
    if res is None:
        return {"error": "The ERP stopped answering while reading the order.",
                "source": "unavailable", "erp_unreachable": True,
                "available_orders": []}
    if "error" in res:
        res.setdefault("not_in_erp", True)
        res.setdefault("warnings", [f"Order '{order_id}' is not in the ERP."])
        res.setdefault("source", "live")
    return res


def _sample_order():
    """The bundled order, marked as a SAMPLE — shown only while the ERP holds no Sales Order."""
    ids = snapshot_order_ids()
    snap = _snapshot_order(ids[0]) if ids else None
    if not snap:
        return None
    snap["source"] = "sample"
    snap["order"]["_source"] = "sample"
    snap["sample"] = True
    snap["warnings"] = ["SAMPLE ORDER — the ERP has no Sales Orders yet, so a bundled example is shown to "
                        "demonstrate the calendar. It disappears as soon as the first order is in the ERP."]
    return snap


def snapshot_order_ids() -> list:
    snap = load_snapshot()
    o = snap.get("order") or {}
    return [o.get("sales_order")] if o.get("sales_order") else []


def list_orders(product_type: str = "", search_query: str = "",
                limit: int = 50, offset: int = 0, force_snapshot: bool = False) -> dict:
    """Return in-scope orders for the picker, read LIVE from the ERP.

    Never invents orders and never substitutes sample data: an ERP with no sales
    orders returns an empty list with a warning, so the UI can say so honestly.
    The bundled snapshot is read only when ``TNA_OFFLINE=1``/``force_snapshot``.
    Never raises."""
    limit = int(limit or 50)
    offset = int(offset or 0)
    warnings: list = []
    orders: list = []
    src = "live"
    error = None

    if force_snapshot or config.TNA_OFFLINE:
        snap = _snapshot_order(config.TEST_ORDER_ID)
        orders = [snap["order"]] if snap else []
        src = "snapshot"
    elif not erp_available():
        src = "unavailable"
        error = "The ERP is not reachable."
        warnings.append(f"The ERP is unreachable ({last_error() or 'no answer'}); no orders can be listed.")
    else:
        try:
            filt = [["docstatus", "<", 2]]       # drafts too: intake creates draft orders (2026-11-07)
            company = _selling_company()
            if company:
                filt.append(["company", "=", company])
            rows = erp_get("Sales Order", fields=["name"], filters=filt,
                           limit=200, order="name asc")
            for so in _fetch_docs_parallel("Sales Order", [r.get("name") for r in rows]):
                orders.append(_order_from_items(so, None, so.get("po_no") or None, None, "live"))
            if not orders:
                if config.TNA_SAMPLE_WHEN_EMPTY and _sample_order():
                    orders = [_sample_order()["order"]]
                    src = "sample"
                    warnings.append("SAMPLE ORDER shown — the ERP has no Sales Orders yet.")
                else:
                    warnings.append("The ERP has no sales orders yet.")
        except Exception as e:
            _set_error(e)
            src = "unavailable"
            error = "The ERP stopped answering while listing orders."
            orders = []
            warnings.append(f"The ERP could not be read ({last_error() or 'no answer'}).")

    if search_query:
        q = str(search_query).lower()
        orders = [o for o in orders
                  if q in str(o.get("sales_order") or "").lower()
                  or q in str(o.get("customer") or "").lower()
                  or q in str(o.get("style_no") or "").lower()
                  or q in str(o.get("style_name") or "").lower()]
    if product_type:
        orders = [o for o in orders
                  if str(o.get("template_id") or config.DEFAULT_PRODUCT_TYPE) == product_type]

    total_count = len(orders)
    page = orders[offset: offset + limit] if limit else orders[offset:]

    items = []
    for o in page:
        items.append({
            "order_id": o.get("sales_order"),
            "customer": o.get("customer"),
            "style_no": o.get("style_no"),
            "style_name": o.get("style_name"),
            "colour": o.get("colour"),
            "qty": o.get("qty"),
            "ship_date": o.get("delivery_date"),
            "sales_order_status": o.get("sales_order_status"),
            "product_type": o.get("template_id") or config.DEFAULT_PRODUCT_TYPE,
            "template_id": o.get("template_id") or config.DEFAULT_PRODUCT_TYPE,
            "source": src,
        })
    return {"orders": items, "total": len(items), "total_count": total_count,
            "offset": offset, "limit": limit, "source": src, "warnings": warnings,
            "error": error, "no_orders": (src == "live" and not orders), "sample": src == "sample"}
