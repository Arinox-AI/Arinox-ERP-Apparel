"""Cortex TnA Calendar — cross-app bridge + new-order intake.

Two jobs:

1. **The Cortex Tower bridge.** The TnA Calendar and the *Cortex Operations Control
   Tower* are **two separate KOGO apps** (different middleware projects). This module is
   the only place the TnA backend talks to the Tower — over the KOGO middleware, with the
   same injected ``API_PATH`` / ``USER_JWT_TOKEN`` the ERP adapter already uses. Every
   call is best-effort and time-boxed: if the Tower is down, the TnA app is unaffected.

2. **New-order intake.** An *intake queue* of orders that have arrived but whose TnA plan
   has not been started yet. Sources:
     * the **ERP** — submitted Sales Orders (always available);
     * the **Tower** — orders/risks the Control Tower already knows about (enrichment).
   Approving an intake row **starts the TnA work** for that order.

Nothing here writes to the ERP. The intake queue lives in the local SQLite overlay.
"""

from __future__ import annotations

import json as _json
from typing import Optional
from urllib.parse import quote as _quote

import requests
from sqlalchemy.orm import Session

from . import config
from . import erp
from .models import AppSettingModel, TnaIntakeModel

# ── Bridge configuration ──────────────────────────────────────────────────────
TOWER_PROJECT = getattr(config, "TOWER_PROJECT", "cortex_operations_control_tower")
# Tower functions we are allowed to call (its *published* set — kept small and read-only).
TOWER_READ_FUNCTIONS = ["get_buyer_orders", "get_risks", "get_dashboard"]
# The sentinel order id used to record the ERP baseline on first sync.
BASELINE_NOTE = "Already in the book when the intake queue was created (baseline)."

# ── Jump-link setting (app → Cortex Tower) ───────────────────────────────────
TOWER_URL_KEY = "tower_app_url"
TOWER_URL_ENV = getattr(config, "TOWER_APP_URL", "") or ""


def _middleware_url() -> str:
    base = (config.KOGO_API_BASE or "").rstrip("/")
    if base:
        return base + "/api/agent/common_project_api_v1"
    # Fall back to deriving the host from API_PATH (…/api/v1/gateway → …/api/... )
    return ""


def _ids() -> dict:
    return {
        "agentId": config.AGENT_ID or "",
        "deploymentId": config.DEPLOYMENT_ID or "",
        "swarmId": config.SWARM_ID or "",
        "originId": config.SWARM_ID or "",
    }


def tower_available() -> bool:
    return bool(_middleware_url() and config.USER_JWT_TOKEN)


def tower_call(function: str, params: Optional[dict] = None, timeout: int = 25) -> dict:
    """Call a function on the Cortex Tower project via the KOGO middleware.

    Returns ``{"ok": bool, "data": ..., "error": ...}`` — never raises.
    """
    url = _middleware_url()
    if not url:
        return {"ok": False, "data": None, "error": "KOGO_API_BASE is not set — bridge unavailable."}
    if not config.USER_JWT_TOKEN:
        return {"ok": False, "data": None, "error": "No user token in this request — bridge unavailable."}
    body = {"project": TOWER_PROJECT, "function": function, "params": params or {}, **_ids()}
    try:
        r = requests.post(
            url,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {config.USER_JWT_TOKEN}"},
            json=body,
            timeout=timeout,
        )
        payload = r.json()
        if payload.get("success") is False:
            return {"ok": False, "data": None, "error": payload.get("message") or "Tower call failed."}
        return {"ok": True, "data": payload.get("data"), "error": None}
    except Exception as e:  # network / timeout / bad JSON
        return {"ok": False, "data": None, "error": f"{type(e).__name__}: {e}"}


def _tower_order_index() -> tuple[dict, Optional[str]]:
    """Best-effort map of ``order_id -> tower facts`` from the Control Tower.

    Returns ``(index, error)``. An empty index with an error simply means the Tower is
    unreachable or has not published the order list — the intake still works off the ERP.
    """
    idx: dict = {}
    res = tower_call("get_buyer_orders", {"limit": 200})
    if not res["ok"]:
        return idx, res["error"]
    data = res["data"] or {}
    rows = data.get("buyer_orders") or data.get("orders") or []
    for o in rows:
        oid = o.get("order_number") or o.get("order_id") or o.get("id") or o.get("name")
        if not oid:
            continue
        idx[str(oid)] = {
            "tower_status": o.get("status") or o.get("overall_status"),
            "tower_rag": o.get("rag"),
            "tower_buyer": o.get("buyer_name") or o.get("customer"),
            "tower_po_no": o.get("po_no"),
            "tower_value": o.get("grand_total"),
            "tower_currency": o.get("currency"),
            "tower_style": o.get("style"),
            "tower_risk_count": 0,
            "tower_risk_titles": [],
        }

    # Attach open risks whose affected_orders / style point at an order we know.
    rr = tower_call("get_risks", {"limit": 200})
    if rr["ok"]:
        for rk in ((rr["data"] or {}).get("risks") or []):
            if (rk.get("status") or "open") != "open":
                continue
            title = rk.get("title") or rk.get("risk_key")
            sev = rk.get("severity")
            targets = [str(x) for x in (rk.get("affected_orders") or [])]
            for oid, entry in idx.items():
                hit = oid in targets
                if not hit and entry.get("tower_style"):
                    material = rk.get("material")
                    hit = bool(material) and str(material) in str(entry.get("tower_style"))
                if hit:
                    entry["tower_risk_count"] += 1
                    if len(entry["tower_risk_titles"]) < 6:
                        entry["tower_risk_titles"].append({"title": title, "severity": sev})
    return idx, None


# ── Intake queue ──────────────────────────────────────────────────────────────

def _upsert_intake(db: Session, order: dict, *, status: str, source: str,
                   tower_context: Optional[dict] = None, tower_ref: Optional[str] = None,
                   note: Optional[str] = None) -> TnaIntakeModel:
    oid = str(order.get("order_id") or order.get("sales_order") or "").strip()
    row = db.query(TnaIntakeModel).filter(TnaIntakeModel.order_id == oid).one_or_none()
    if row is None:
        row = TnaIntakeModel(order_id=oid)
        db.add(row)
    row.customer = order.get("customer")
    row.style_no = order.get("style_no")
    row.style_name = order.get("style_name")
    row.qty = order.get("qty")
    row.ship_date = order.get("ship_date")
    row.product_type = order.get("product_type") or order.get("template_id")
    # never silently downgrade a decided row back to 'detected'
    if row.status in (None, "", "detected", "snoozed") or status in ("approved", "rejected"):
        row.status = status
    row.source = row.source or source
    if tower_context:
        row.tower_context = _json.dumps(tower_context)
    if tower_ref:
        row.tower_ref = tower_ref
    if note:
        row.note = note
    return row


def sync_intake(db: Session, force: bool = False) -> dict:
    """Refresh the intake queue from the ERP (+ Tower enrichment).

    The queue mirrors the ERP. It never adds an order the ERP does not hold, and when
    an order leaves the ERP (cancelled or deleted) its row is marked **withdrawn**, so
    the notifications always match the real order book instead of an old snapshot.

    * First run against a live ERP records the current orders as an **approved
      baseline**, so the inbox does not flood with orders that were already in the book.
    * Any order seen afterwards that is not yet known lands as **detected** = a new
      notification.
    """
    erp_res = erp.list_orders(limit=200)
    orders = erp_res.get("orders") or []
    source = erp_res.get("source") or "live"
    # Only a successful LIVE read is authoritative. A failed read must never be read
    # as "the ERP has no orders" and empty the queue.
    live_ok = source == "live" and not erp_res.get("error")

    tower_idx, tower_err = ({}, None)
    if force or True:  # always attempt; cheap and time-boxed
        tower_idx, tower_err = _tower_order_index()

    existing = {r.order_id: r for r in db.query(TnaIntakeModel).all()}
    first_run = len(existing) == 0

    created = []
    enriched = []
    seen: set = set()
    for o in orders:
        oid = str(o.get("order_id") or "")
        if not oid:
            continue
        seen.add(oid)
        ctx = tower_idx.get(oid)
        if first_run:
            _upsert_intake(db, o, status="approved", source="erp",
                           tower_context=ctx, note=BASELINE_NOTE)
            continue
        if oid in existing:
            if ctx and not existing[oid].tower_context:
                existing[oid].tower_context = _json.dumps(ctx)
                enriched.append(oid)
            continue
        _upsert_intake(db, o, status="detected", source="erp", tower_context=ctx,
                       note="New order detected — approve to start its TnA plan.")
        created.append(oid)

    # Reconcile: anything we hold that the live ERP no longer holds is withdrawn.
    withdrawn = []
    if live_ok:
        for oid, row in existing.items():
            if oid in seen or (row.status or "") in ("withdrawn", "rejected"):
                continue
            row.status = "withdrawn"
            row.note = "This order is no longer in the ERP, so it was removed from the queue."
            withdrawn.append(oid)

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "source": source,
        "first_run": first_run,
        "orders_seen": len(orders),
        "detected": created,
        "detected_count": len(created),
        "withdrawn": withdrawn,
        "withdrawn_count": len(withdrawn),
        "enriched_from_tower": enriched,
        "no_orders": bool(erp_res.get("no_orders")),
        "erp_error": erp_res.get("error"),
        "tower": {"reachable": tower_err is None, "error": tower_err,
                  "orders_known": len(tower_idx)},
        "warnings": erp_res.get("warnings") or [],
    }


def list_intake(db: Session, status: str = "", sync: bool = True) -> dict:
    if sync:
        sync_intake(db)
    q = db.query(TnaIntakeModel)
    if status:
        q = q.filter(TnaIntakeModel.status == status)
    else:
        # Withdrawn rows are kept for history but are no longer notifications.
        q = q.filter(TnaIntakeModel.status != "withdrawn")
    rows = q.order_by(TnaIntakeModel.status.asc(), TnaIntakeModel.id.desc()).all()
    items = [r.to_dict() for r in rows]
    # Attach a deep link into the Cortex Tower so the UI can offer a jump.
    for it in items:
        it["tower_link"] = build_tower_link(db, it.get("order_id") or "")
    withdrawn = db.query(TnaIntakeModel).filter(TnaIntakeModel.status == "withdrawn").count()
    summary = {
        "total": len(items),
        "pending": sum(1 for i in items if i["status"] == "detected"),
        "approved": sum(1 for i in items if i["status"] == "approved"),
        "rejected": sum(1 for i in items if i["status"] == "rejected"),
        "snoozed": sum(1 for i in items if i["status"] == "snoozed"),
        "withdrawn": withdrawn,
        "from_tower": sum(1 for i in items if i.get("tower_context")),
    }
    return {"notifications": items, "summary": summary, "bridge": bridge_status(db)}


def decide_intake(db: Session, order_id: str, decision: str, actor: str = "",
                  note: str = "") -> dict:
    """Approve (start the TnA plan), reject, or snooze an intake row."""
    oid = (order_id or "").strip()
    if not oid:
        return {"error": "order_id is required."}
    decision = (decision or "").strip().lower()
    if decision not in ("approved", "rejected", "snoozed", "detected"):
        return {"error": f"Unknown decision '{decision}'. Use approved|rejected|snoozed."}

    row = db.query(TnaIntakeModel).filter(TnaIntakeModel.order_id == oid).one_or_none()
    if row is None:
        # allow approving an order that was never queued (manual start)
        orders = (erp.list_orders(search_query=oid, limit=5).get("orders") or [])
        match = next((o for o in orders if str(o.get("order_id")) == oid), None)
        if not match:
            return {"error": f"Order '{oid}' not found in the ERP."}
        row = _upsert_intake(db, match, status=decision, source="manual")
    row.status = decision
    if actor:
        row.actor = actor
    if note:
        row.note = note
    from datetime import datetime, timezone
    row.decided_at = datetime.now(timezone.utc)

    # Cross-app: best-effort notify the Tower that this order was actioned in TnA.
    tower_notice = None
    if decision == "approved":
        tower_notice = tower_call("get_dashboard", {"inbox_action": ""})
    try:
        db.commit()
    except Exception:
        db.rollback()
        return {"error": "Could not save the decision."}

    out = {
        "order_id": oid,
        "decision": decision,
        "status": row.status,
        "started": decision == "approved",
        "record": row.to_dict(),
        "tower_notified": bool(tower_notice and tower_notice.get("ok")),
        "message": (
            f"Approved — the TnA plan for {oid} is now live in the calendar."
            if decision == "approved" else
            f"Order {oid} marked {decision}."
        ),
    }
    if decision == "approved" and tower_notice and not tower_notice.get("ok"):
        out["tower_warning"] = tower_notice.get("error")
    return out


def bridge_status(db: Session = None) -> dict:
    """Health of the cross-app link — surfaced to the UI as a badge + a jump link."""
    erp_st = {}
    try:
        erp_st = erp.erp_status()
    except Exception as e:
        erp_st = {"connected": False, "error": str(e)}
    reachable = tower_available()
    url = get_tower_app_url(db)
    return {
        "tower_project": TOWER_PROJECT,
        "tower_configured": reachable,
        "tower_functions": TOWER_READ_FUNCTIONS,
        "tower_app_url": url or None,
        "tower_jump_enabled": bool(url),
        "tower_url_source": ("env" if _env_tower_url() else ("saved" if url else None)),
        "erp": {"connected": bool(erp_st.get("connected")), "base": erp_st.get("base"),
                "error": erp_st.get("error")},
        "note": ("Linked to Cortex Tower over the KOGO middleware. Approvals in TnA are "
                 "visible here; Tower notifications flow into the TnA intake queue."),
    }


# ── Jump link: TnA → Cortex Tower ────────────────────────────────────────────

def _env_tower_url() -> str:
    return (TOWER_URL_ENV or "").strip()


def get_tower_app_url(db: Session = None) -> str:
    """The Cortex Tower app URL. Env wins; otherwise the value saved in the app."""
    env = _env_tower_url()
    if env:
        return env
    if db is None:
        return ""
    try:
        row = db.query(AppSettingModel).filter(AppSettingModel.key == TOWER_URL_KEY).one_or_none()
        return (row.value or "").strip() if row else ""
    except Exception:
        return ""


def _valid_url(u: str) -> bool:
    u = (u or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def set_tower_app_url(db: Session, url: str, actor: str = "") -> dict:
    url = (url or "").strip()
    if url and not _valid_url(url):
        return {"error": "Enter a full URL starting with http:// or https://"}
    try:
        row = db.query(AppSettingModel).filter(AppSettingModel.key == TOWER_URL_KEY).one_or_none()
        if row is None:
            row = AppSettingModel(key=TOWER_URL_KEY)
            db.add(row)
        row.value = url or None
        row.updated_by = actor or None
        db.commit()
    except Exception as e:
        db.rollback()
        return {"error": f"Could not save the link: {e}"}
    return {
        "ok": True, "tower_app_url": url or None, "jump_enabled": bool(url),
        "message": ("Cortex Tower link saved." if url else "Cortex Tower link cleared."),
    }


def build_tower_link(db: Session = None, order_id: str = "") -> Optional[str]:
    """A deep link into the Cortex Tower. The order id is appended when present so a
    Tower build that reads it can open the right order; a Tower that ignores it simply
    lands on its home screen."""
    base = get_tower_app_url(db)
    if not base:
        return None
    if not order_id:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}order_id={_quote(str(order_id), safe='')}"
