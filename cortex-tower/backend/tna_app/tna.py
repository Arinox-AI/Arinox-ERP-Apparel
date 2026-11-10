"""Cortex TnA Calendar — the Time & Action engine (SPEC §7–§10).

Pure Python (stdlib + optional ``python-dateutil``). No I/O beyond reading the
bundled template + holiday JSON files. Deterministic: given the same order,
template, calendar, overlay and ``as_of`` the output is byte-identical.

Provides:

* :class:`WorkingCalendar` — ``is_working`` / ``shift`` / ``working_days_between``
  over the bundled VN / CN / HK calendars (day-by-day stepping, never
  calendar-day arithmetic).
* ``load_template`` / ``load_holidays`` — data-driven template + calendar loaders.
* ``build_calendar`` — backward schedule from SHIP, merge actuals, derive
  status / delay / dependency blocking / critical path.
* ``kpis`` — the delivery KPIs (SPEC §9).
* ``exceptions`` — the ranked exception list + deterministic next action (SPEC §10).
"""

from __future__ import annotations

import glob
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import config
DATA_DIR = Path(__file__).resolve().parent / "data"

COMPLETED = ("Completed", "Completed late")

_STATUS_RANK = {"Blocked": 0, "Overdue": 1, "At risk": 2, "Not recorded": 3}


# ────────────────────────────────────────────────────────────────────────────
# Loading helpers
# ────────────────────────────────────────────────────────────────────────────

def _today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _template_files() -> list:
    """Every ``tna_template_*.json`` in backend/data/ (data-driven extensibility)."""
    files = sorted(glob.glob(str(DATA_DIR / "tna_template_*.json")))
    return [Path(f) for f in files]


def load_template(template_id: str = "") -> dict:
    """Load a product-type TnA template. ``template_id`` may match the template id
    **or** the product-type string (case-insensitive). Unknown → error dict listing
    the available templates (never raises)."""
    wanted = (template_id or config.DEFAULT_PRODUCT_TYPE).strip()
    found = []
    for path in _template_files():
        try:
            raw = _read_json(path)
        except Exception:
            continue
        found.append(raw)
    if not found:
        return {"error": "No TnA template files found in backend/data/", "available": []}

    match = None
    for raw in found:
        if str(raw.get("template_id") or "").lower() == wanted.lower():
            match = raw
            break
    if match is None:
        for raw in found:
            if str(raw.get("product_type") or "").lower() == wanted.lower():
                match = raw
                break
    if match is None:
        return {"error": f"Template '{wanted}' not found",
                "available": [r.get("template_id") for r in found],
                "product_types": [r.get("product_type") for r in found],
                "source": "file"}

    milestones = [dict(m) for m in (match.get("milestones") or [])]
    return {
        "template_id": match.get("template_id"),
        "product_type": match.get("product_type"),
        "description": match.get("description"),
        "calendar": match.get("calendar") or config.DEFAULT_CALENDAR,
        "anchor": match.get("anchor") or "SHIP",
        "schedule_direction": match.get("schedule_direction") or "backward",
        "categories": list(match.get("categories") or []),
        "owner_roles": list(match.get("owner_roles") or []),
        "milestone_count": len(milestones),
        "milestones": milestones,
        "source": "file",
    }


def _normalize_calendar(cal_id: str, raw: dict, year) -> dict:
    return {
        "calendar": cal_id,
        "label": raw.get("label") or cal_id,
        "country": raw.get("country") or "",
        "tz": raw.get("tz") or "",
        "year": year,
        "working_weekdays": [int(x) for x in (raw.get("working_weekdays") or [])],
        "working_week_label": raw.get("working_week_label") or "",
        "holidays": dict(raw.get("holidays") or {}),
        "special_working_days": list(raw.get("special_working_days") or []),
        "source": "file",
        "note": "Working-day maths = working_weekdays MINUS holidays PLUS special_working_days.",
    }


def _holiday_file() -> dict:
    path = DATA_DIR / config.HOLIDAYS_FILE
    try:
        return _read_json(path)
    except Exception:
        return {}


def load_holidays(calendar_id: str = "") -> dict:
    """Return one HolidayCalendar, or all of them under ``{"calendars": {...}}``
    when ``calendar_id`` is empty. Unknown id → error dict with the available ids."""
    raw = _holiday_file()
    calendars = raw.get("calendars") or {}
    year = raw.get("year")
    available = list(calendars.keys())

    if not calendar_id:
        return {
            "calendars": {cid: _normalize_calendar(cid, c, year) for cid, c in calendars.items()},
            "available": available,
            "source": "file",
            "year": year,
        }
    if calendar_id not in calendars:
        return {"error": f"Calendar '{calendar_id}' not found", "available": available}
    out = _normalize_calendar(calendar_id, calendars[calendar_id], year)
    out["weekday_numbering"] = raw.get("weekday_numbering")
    return out


def list_calendar_ids() -> list:
    return list((_holiday_file().get("calendars") or {}).keys())


# ────────────────────────────────────────────────────────────────────────────
# Working-day calendar
# ────────────────────────────────────────────────────────────────────────────

def _as_date(d) -> Optional[date]:
    if d is None or d == "":
        return None
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except Exception:
        return None


class WorkingCalendar:
    """Working-day arithmetic over one calendar (SPEC §7.2)."""

    def __init__(self, cal: dict):
        self.data = cal or {}
        self.id = cal.get("calendar") or "VN_FACTORY"
        self.working = {int(x) for x in (cal.get("working_weekdays") or [1, 2, 3, 4, 5, 6])}
        self.holidays = {str(k): v for k, v in (cal.get("holidays") or {}).items()}
        self.special = {str(x) for x in (cal.get("special_working_days") or [])}

    def is_working(self, day) -> bool:
        d = _as_date(day)
        if d is None:
            return False
        key = d.isoformat()
        if key in self.holidays:
            return False
        return (d.isoweekday() in self.working) or (key in self.special)

    def shift(self, day, n: int) -> Optional[date]:
        """Move ``n`` working days from ``day`` (spec: offset 0 returns the anchor
        unchanged, even if it is not a working day)."""
        d = _as_date(day)
        if d is None:
            return None
        n = int(n or 0)
        if n == 0:
            return d
        step = 1 if n > 0 else -1
        remaining = abs(n)
        cur = d
        guard = 0
        while remaining > 0 and guard < 4000:
            cur = cur + timedelta(days=step)
            if self.is_working(cur):
                remaining -= 1
            guard += 1
        return cur

    def working_days_between(self, a, b) -> int:
        """Signed working-day distance ``a → b`` (0 when equal; >0 when b is later)."""
        da, db = _as_date(a), _as_date(b)
        if da is None or db is None:
            return 0
        if da == db:
            return 0
        step = 1 if db > da else -1
        cur = da
        n = 0
        guard = 0
        while cur != db and guard < 8000:
            cur = cur + timedelta(days=step)
            if self.is_working(cur):
                n += 1
            guard += 1
        return n * step

    def holidays_in(self, a, b) -> list:
        da, db = _as_date(a), _as_date(b)
        if da is None or db is None or db < da:
            return []
        out = []
        cur = da
        while cur <= db:
            key = cur.isoformat()
            if key in self.holidays and cur.isoweekday() in self.working:
                out.append({"date": key, "label": self.holidays[key]})
            cur = cur + timedelta(days=1)
        return out

    def next_working_day(self, day):
        d = _as_date(day)
        if d is None:
            return None
        return self.shift(d, 1)

    def prev_working_day(self, day):
        d = _as_date(day)
        if d is None:
            return None
        return self.shift(d, -1)


def calendar_for(calendar_id: str = "") -> WorkingCalendar:
    cal = load_holidays(calendar_id or config.DEFAULT_CALENDAR)
    if "error" in cal:
        cal = load_holidays(config.DEFAULT_CALENDAR)
    return WorkingCalendar(cal)


# ────────────────────────────────────────────────────────────────────────────
# Status derivation (SPEC §8.2)
# ────────────────────────────────────────────────────────────────────────────

def derive_status(row: dict, defn: dict, planned_start, planned_finish, today,
                  cal: WorkingCalendar, status_by_code: dict, category_by_code: dict,
                  not_recorded_codes: list, window: int):
    """Return ``(status, status_source, blocked_by, is_blocked)`` — first match wins."""
    code = row["code"]
    planned_start = _as_date(planned_start)
    planned_finish = _as_date(planned_finish)
    today = _as_date(today)
    deps = list(defn.get("depends_on") or [])
    unmet = [d for d in deps if status_by_code.get(d) not in COMPLETED]

    if row.get("status_override"):
        ov = row["status_override"]
        return ov, "override", ([d for d in deps] if ov == "Blocked" else []), (ov == "Blocked")

    if row.get("actual_finish"):
        wd = cal.working_days_between(planned_finish, row["actual_finish"]) if planned_finish else 0
        return ("Completed late" if wd > 0 else "Completed"), "computed", [], False

    if row.get("actual_start"):
        return "In progress", "computed", [], False

    if code in (not_recorded_codes or []) and not row.get("evidence_retrieved"):
        return "Not recorded", "computed", [], False

    if planned_finish is None:
        return "Not started", "computed", [], False

    if planned_finish < today:
        return "Overdue", "computed", [], False

    blocked_preds = [d for d in deps if status_by_code.get(d) == "Blocked"]
    if blocked_preds:
        return "Blocked", "computed", blocked_preds, True

    if unmet and planned_start and planned_start <= today:
        if any(category_by_code.get(d) == "Material" for d in unmet):
            return "Waiting for material", "computed", unmet, False
        if row.get("requires_approval"):
            return "Waiting for approval", "computed", unmet, False
        if row.get("is_critical"):
            return "Blocked", "computed", unmet, True
        return "At risk", "computed", unmet, True

    if row.get("requires_approval"):
        return "Waiting for approval", "computed", [], False

    if cal.working_days_between(today, planned_finish) <= window:
        return "At risk", "computed", [], False

    return "Not started", "computed", [], False


def next_action_text(row: dict) -> str:
    """Deterministic next action for an exception (SPEC §10)."""
    status = row.get("status")
    owner = row.get("owner_role") or row.get("owner") or ""
    if status == "Overdue":
        return f"Record actual or re-plan — chase {owner} (planned finish {row.get('planned_finish') or '—'})."
    if status == "At risk":
        return f"Confirm {owner} can finish by {row.get('planned_finish') or '—'}."
    if status == "Blocked":
        by = ", ".join(row.get("blocked_by") or []) or "predecessor"
        return f"Unblock predecessor {by} before {row.get('planned_start') or '—'}."
    if status == "Waiting for approval":
        return f"Chase approval from {owner}."
    if status == "Waiting for material":
        return f"Chase material in-house from {owner}."
    if status == "Not recorded":
        return f"Record evidence from {row.get('evidence_source') or 'the source document'}."
    return "Monitor."


# ────────────────────────────────────────────────────────────────────────────
# KPIs (SPEC §9) + exceptions (SPEC §10)
# ────────────────────────────────────────────────────────────────────────────

def _count(rows, status) -> int:
    return sum(1 for r in rows if r.get("status") == status)


def build_exceptions(rows: list) -> list:
    """Milestones needing attention, ranked (critical status first).

    Ranking: ``(status_rank, -delay_days, seq)``. This reproduces SPEC §16.1's
    pinned ``next_action`` (SALES_CONTRACT) for the canonical run."""
    ex = [r for r in rows if r.get("status") in _STATUS_RANK]
    ex.sort(key=lambda r: (_STATUS_RANK.get(r.get("status"), 9),
                           -int(r.get("delay_days") or 0),
                           int(r.get("seq") or 0)))
    for r in ex:
        r["next_action_text"] = next_action_text(r)
        r["rank_reason"] = f"{r.get('status')} · {r.get('delay_days')} wd"
    return ex


# ── Alerts, escalation + owner workload (2026-10-07) ────────────────────────

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# status → (kind, base severity, aged in working days)
_ALERT_KIND = {
    "Overdue": ("overdue", "high", True),
    "Blocked": ("blocked", "high", True),
    "At risk": ("at_risk", "medium", False),
    "Waiting for approval": ("awaiting_approval", "medium", False),
    "Waiting for material": ("awaiting_material", "high", True),
    "Not recorded": ("not_recorded", "low", False),
}


def _escalation_level(days_open: int, l1: int, l2: int) -> int:
    if days_open <= l1:
        return 1
    if days_open <= l2:
        return 2
    return 3


def build_alerts(rows: list, as_of: str, cal: WorkingCalendar,
                 wd_l1: int = 3, wd_l2: int = 10) -> list:
    """Ranked, escalated alerts for every milestone that needs attention.

    Each alert carries severity, kind, active owner, working-days open, an
    escalation level + target, and the deterministic next action. Sorted by
    (severity, −days_open, seq)."""
    as_of_d = _as_date(as_of) or _as_date(_today_iso())
    out: list = []
    for r in rows:
        kind, base_sev, aged = _ALERT_KIND.get(r.get("status"), (None, None, False))
        needs_reason = bool(r.get("needs_attribution"))
        if not kind and not needs_reason:
            continue
        pf = _as_date(r.get("planned_finish"))
        af = _as_date(r.get("actual_finish"))
        days_open = 0
        if aged and pf:
            days_open = max(0, int(cal.working_days_between(pf, af or as_of_d)))
        severity = base_sev or "low"
        if r.get("is_critical") and severity in ("high", "medium"):
            severity = "critical"
        level = _escalation_level(days_open, wd_l1, wd_l2) if kind else 0
        owner = r.get("owner") or r.get("owner_role") or ""
        tags = []
        if not owner:
            tags.append("unassigned")
        if r.get("manual"):
            tags.append("manual")
        if needs_reason:
            tags.append("missing_reason")
        if r.get("is_critical"):
            tags.append("critical_path")
        out.append({
            "code": r["code"], "name": r["name"], "category": r["category"], "seq": r["seq"],
            "kind": kind or "missing_reason",
            "severity": severity,
            "status": r.get("status"),
            "owner": r.get("owner"), "owner_role": r.get("owner_role"),
            "assigned_to": owner or "Unassigned",
            "is_critical": bool(r.get("is_critical")),
            "manual": bool(r.get("manual")),
            "planned_finish": r.get("planned_finish"),
            "actual_finish": r.get("actual_finish"),
            "forecast_finish": r.get("forecast_finish"),
            "days_open": days_open,
            "delay_days": r.get("delay_days"),
            "escalation_level": level,
            "escalate_to": config.ESCALATION_TARGETS.get(level, "Owner") if level else None,
            "tags": tags,
            "next_action_text": next_action_text(r),
            "evidence_source": r.get("evidence_source"),
        })
    out.sort(key=lambda a: (_SEVERITY_RANK.get(a["severity"], 9),
                            -int(a.get("days_open") or 0), int(a.get("seq") or 0)))
    return out


def alert_summary(alerts: list, total: int) -> dict:
    """Counts for the alerts header + KPI strip."""
    from collections import Counter
    kinds = Counter(a["kind"] for a in alerts)
    sevs = Counter(a["severity"] for a in alerts)
    levels = Counter(a["escalation_level"] for a in alerts if a["escalation_level"])
    owners = Counter(a["assigned_to"] for a in alerts)
    return {
        "total": len(alerts),
        "critical": sevs.get("critical", 0),
        "high": sevs.get("high", 0),
        "medium": sevs.get("medium", 0),
        "low": sevs.get("low", 0),
        "by_kind": dict(kinds),
        "escalation_level_3": levels.get(3, 0),
        "escalation_level_2": levels.get(2, 0),
        "escalation_level_1": levels.get(1, 0),
        "unassigned": sum(1 for a in alerts if "unassigned" in a["tags"]),
        "manual": sum(1 for a in alerts if a["manual"]),
        "missing_reason": sum(1 for a in alerts if "missing_reason" in a["tags"]),
        "max_escalation": max([a["escalation_level"] for a in alerts] or [0]),
        "top_owner": (owners.most_common(1)[0][0] if owners else None),
        "milestones_total": total,
    }


def build_owner_workload(rows: list) -> dict:
    """Milestone workload grouped by the effective owner (name, else role)."""
    groups: dict = {}
    for r in rows:
        name = r.get("owner") or r.get("owner_role") or "Unassigned"
        g = groups.setdefault(name, {
            "owner": name, "role": r.get("owner_role") or "",
            "total": 0, "completed": 0, "overdue": 0, "at_risk": 0, "blocked": 0,
            "awaiting": 0, "critical": 0, "manual": 0, "progress_sum": 0.0, "codes": [],
        })
        g["total"] += 1
        st = r.get("status")
        if st in COMPLETED:
            g["completed"] += 1
        if st == "Overdue":
            g["overdue"] += 1
        if st == "At risk":
            g["at_risk"] += 1
        if st == "Blocked":
            g["blocked"] += 1
        if st in ("Waiting for approval", "Waiting for material"):
            g["awaiting"] += 1
        if r.get("is_critical"):
            g["critical"] += 1
        if r.get("manual"):
            g["manual"] += 1
        g["progress_sum"] += float(r.get("progress_pct") or 0)
        g["codes"].append(r["code"])
    owners = []
    for g in groups.values():
        g["progress_pct"] = round(g["progress_sum"] / g["total"], 1) if g["total"] else 0.0
        g["open"] = g["total"] - g["completed"]
        g.pop("progress_sum", None)
        owners.append(g)
    owners.sort(key=lambda x: (-x["open"], x["owner"]))
    return {"owners": owners, "total": len(owners),
            "unassigned": next((o for o in owners if o["owner"] == "Unassigned"), None)}


def alert_digest(header: dict, alerts: list, summary: dict, as_of: str) -> str:
    """Plain-text reminder digest (ready to email / paste into chat)."""
    lines = [
        f"TnA alert digest — {header.get('order_id')} · {header.get('customer') or ''}",
        f"As of {as_of} · ship {header.get('ship_date')} · "
        f"{summary.get('total', 0)} open alerts ({summary.get('critical', 0)} critical)",
        "",
    ]
    for a in alerts[:15]:
        esc = f" · escalate L{a['escalation_level']} → {a['escalate_to']}" if a.get("escalation_level") else ""
        lines.append(f"- [{a['severity'].upper()}] {a['code']} ({a['status']}, {a['days_open']} wd open)"
                     f" · owner {a['assigned_to']}{esc}")
        lines.append(f"    {a['next_action_text']}")
    if len(alerts) > 15:
        lines.append(f"… and {len(alerts) - 15} more.")
    return "\n".join(lines)


def kpis(rows: list, header: dict, cal: WorkingCalendar, as_of: str) -> dict:
    required = header.get("ship_date")
    done = [r for r in rows if r.get("status") in COMPLETED]
    completed_on_time = sum(1 for r in done if r.get("status") == "Completed")
    completed_late = sum(1 for r in done if r.get("status") == "Completed late")
    on_time_pct = round(100.0 * completed_on_time / len(done), 1) if done else None

    criticals = [r for r in rows if r.get("is_critical")]
    crit_dates = [r["actual_finish"] for r in criticals if r.get("actual_finish")]
    crit_delays = [int(r.get("delay_days") or 0) for r in criticals if r.get("actual_finish")]
    critical_path_delay_days = max([0] + crit_delays)
    latest_critical_actual = max(crit_dates) if crit_dates else None

    all_dates = [r["actual_finish"] for r in rows if r.get("actual_finish")]
    latest_actual = max(all_dates) if all_dates else None

    overdue_count = _count(rows, "Overdue")
    at_risk_count = _count(rows, "At risk")
    blocked_count = _count(rows, "Blocked")
    wait_appr = _count(rows, "Waiting for approval")
    wait_mat = _count(rows, "Waiting for material")
    in_progress = _count(rows, "In progress")
    not_started = _count(rows, "Not started")
    not_recorded = _count(rows, "Not recorded")

    if required:
        projected = required
        if critical_path_delay_days:
            projected = max(projected, cal.shift(required, critical_path_delay_days).isoformat())
        if latest_critical_actual:
            projected = max(projected, latest_critical_actual)
        days_to_ship = cal.working_days_between(as_of, required)
        ship_overdue_days = (cal.working_days_between(required, as_of)
                             if str(as_of) > str(required) else 0)
        projected_slip_days = max(0, cal.working_days_between(required, projected))
        if projected <= required:
            on_time_vs_required = "On time"
        else:
            on_time_vs_required = f"Late by {projected_slip_days} working days"
    else:
        projected = None
        days_to_ship = None
        ship_overdue_days = 0
        projected_slip_days = None
        on_time_vs_required = "Unknown"

    un_attributed = sum(1 for r in rows if int(r.get("delay_days") or 0) > 0 and not r.get("delay_reason"))

    if overdue_count > 0 or blocked_count > 0 or (projected and required and projected > required):
        rag = "red"
    elif (at_risk_count > 0 or not_recorded > 0 or wait_appr > 0 or wait_mat > 0
          or (on_time_pct is not None and on_time_pct < 100)):
        rag = "amber"
    else:
        rag = "green"

    ex = build_exceptions(rows)
    nxt = None
    if ex:
        e = ex[0]
        nxt = {"code": e.get("code"), "name": e.get("name"), "owner_role": e.get("owner_role"),
               "status": e.get("status"), "delay_days": e.get("delay_days"),
               "next_action_text": e.get("next_action_text")}

    return {
        "on_time_pct": on_time_pct,
        "completed_count": len(done),
        "completed_on_time_count": completed_on_time,
        "completed_late_count": completed_late,
        "overdue_count": overdue_count,
        "at_risk_count": at_risk_count,
        "blocked_count": blocked_count,
        "waiting_approval_count": wait_appr,
        "waiting_material_count": wait_mat,
        "in_progress_count": in_progress,
        "not_started_count": not_started,
        "not_recorded_count": not_recorded,
        "total_milestones": len(rows),
        "critical_total": len(criticals),
        "critical_completed_count": sum(1 for r in criticals if r.get("status") in COMPLETED),
        "critical_late_count": sum(1 for r in criticals if r.get("status") == "Completed late"),
        "critical_path_delay_days": critical_path_delay_days,
        "days_to_ship": days_to_ship,
        "ship_overdue_days": ship_overdue_days,
        "latest_actual_finish": latest_actual,
        "latest_critical_actual_finish": latest_critical_actual,
        "projected_ship_date": projected,
        "required_ship_date": required,
        "projected_slip_days": projected_slip_days,
        "on_time_vs_required": on_time_vs_required,
        "un_attributed_lates": un_attributed,
        "rag": rag,
        "next_action": nxt,
    }


# ────────────────────────────────────────────────────────────────────────────
# Calendar build
# ────────────────────────────────────────────────────────────────────────────

def _cal_map(cids) -> dict:
    """WorkingCalendar for each requested id (missing ids fall back to default)."""
    out: dict = {}
    for cid in cids:
        if not cid or cid in out:
            continue
        d = load_holidays(cid)
        if "error" not in d:
            out[cid] = WorkingCalendar(d)
    return out


def _compute_cpm(rows: list, anchor_code: str, cal: WorkingCalendar) -> None:
    """Compute the critical path + float from the *dependency graph + durations*.

    A true CPM: forward pass gives each milestone an earliest start (0 = first
    working day of the plan); backward pass from the anchor (SHIP) gives the
    latest start; ``float_days = latest_start - earliest_start``. Milestones with
    ``float <= 0`` **and** a dependency path to the anchor are on the critical path.

    Durations and dependencies drive the path (not the offset lead times), which
    is the standard definition. Milestones with no path to the anchor (e.g. audit
    gates that block nothing specific) get ``float = None`` and are not critical.
    This replaces the hardcoded template ``is_critical`` flag (kept as
    ``is_critical_template``).
    """
    by = {r["code"]: r for r in rows}
    preds = {r["code"]: [d for d in (r.get("depends_on") or []) if d in by] for r in rows}
    succ: dict = {r["code"]: [] for r in rows}
    for r in rows:
        for d in preds[r["code"]]:
            succ[d].append(r["code"])
    dur = {r["code"]: max(1, int(r.get("duration_days") or 1)) for r in rows}

    # Forward pass (earliest start / finish, in working-day units).
    ES: dict = {}
    EF: dict = {}
    for r in sorted(rows, key=lambda x: int(x.get("seq") or 0)):
        code = r["code"]
        es = max([EF[d] for d in preds[code]], default=0)
        ES[code] = es
        EF[code] = es + dur[code]

    # Backward pass (latest finish / start).
    LF: dict = {}
    LS: dict = {}
    for r in sorted(rows, key=lambda x: -int(x.get("seq") or 0)):
        code = r["code"]
        if code == anchor_code:
            lf = EF.get(code)
        else:
            cands = [LS[s] for s in succ.get(code, []) if LS.get(s) is not None]
            lf = min(cands) if cands else None
        LF[code] = lf
        LS[code] = (lf - dur[code]) if lf is not None else None

    for r in rows:
        code = r["code"]
        ls = LS.get(code)
        es = ES.get(code)
        if ls is not None and es is not None:
            f = int(ls - es)
            r["float_days"] = f
            r["on_critical_path"] = bool(f <= 0)
        else:
            r["float_days"] = None
            r["on_critical_path"] = False
        r["is_critical_template"] = bool(r.get("is_critical"))
        r["is_critical"] = bool(r.get("on_critical_path"))


def _progress_pct(row: dict, qty, order_qty) -> float:
    """Per-milestone completion percentage.

    Completed / Completed late → 100. ``In progress`` → qty-based where the
    milestone carries a production quantity, else 50. Everything else → 0.
    """
    st = row.get("status")
    if st in COMPLETED:
        return 100.0
    if st == "In progress":
        try:
            if qty and order_qty:
                return round(min(99.0, 100.0 * float(qty) / float(order_qty)), 1)
        except Exception:
            pass
        return 50.0
    return 0.0


def build_calendar(norm: dict, template: dict, calendar_id: str = "",
                   as_of: str = "", overlay: Optional[dict] = None) -> dict:
    """Backward-schedule the plan and merge actuals + overlay.

    ``norm`` is the normalized order dict from ``erp.fetch_order``; ``overlay``
    maps ``milestone_code -> {actual_start, actual_finish, status_override,
    delay_reason, owner, note}`` for the human layer.
    """
    order = norm.get("order") or {}
    actuals = norm.get("actuals") or {}
    source = norm.get("source") or "snapshot"
    overlay = overlay or {}
    today = _as_date(as_of) or _as_date(_today_iso())
    today_iso = today.isoformat()

    default_cid = calendar_id or template.get("calendar") or config.DEFAULT_CALENDAR
    defs = template.get("milestones") or []
    wanted = {default_cid} | {(m.get("calendar") or default_cid) for m in defs}
    cal_map = _cal_map(wanted)
    if default_cid not in cal_map:
        default_cid = config.DEFAULT_CALENDAR
        cal_map.update(_cal_map({default_cid}))
    cal = cal_map.get(default_cid) or calendar_for(default_cid)
    cid = default_cid
    cal_data = load_holidays(cid)
    if "error" in cal_data:
        cal_data = load_holidays(config.DEFAULT_CALENDAR)

    ship = order.get("delivery_date")
    category_by_code = {m.get("code"): m.get("category") for m in defs}

    rows: list = []
    for m in defs:
        code = m.get("code")
        offset = int(m.get("offset_days") or 0)
        dur = int(m.get("duration_days") or 1)
        mcid = m.get("calendar") or cid
        mcal = cal_map.get(mcid) or cal
        p_finish = mcal.shift(ship, offset) if ship else None
        if p_finish is None:
            p_start = None
        elif dur <= 1:
            p_start = p_finish
        else:
            p_start = mcal.shift(p_finish, -(dur - 1))

        ov = overlay.get(code) or {}
        act = actuals.get(code) or {}

        # The ERP adapter returns the activity *window* (first .. last evidence day).
        # A completion milestone (`*_END`) whose last evidence day is itself a working
        # day is reported as a point (the finish). When the window ends on a
        # non-working day (e.g. packing still recorded on a Sunday) the full window is
        # surfaced instead — this reproduces SPEC §16.1 exactly (SEW_END point vs
        # PACK_END window) and never affects status/delay (which use actual_finish).
        erp_start, erp_finish = act.get("start"), act.get("finish")
        if code.endswith("_END") and erp_finish and cal.is_working(erp_finish):
            erp_start = erp_finish

        a_start = ov.get("actual_start") or erp_start
        a_finish = ov.get("actual_finish") or erp_finish
        from_overlay = bool(ov.get("actual_start") or ov.get("actual_finish"))
        retrieved = bool(act.get("retrieved"))

        if from_overlay:
            evidence_value = ov.get("actual_finish") or ov.get("actual_start") or act.get("evidence_value")
        elif retrieved:
            evidence_value = act.get("evidence_value")
        else:
            evidence_value = None

        if from_overlay:
            data_source = "overlay"
        elif retrieved:
            data_source = "erp"
        else:
            data_source = "none"

        delay = cal.working_days_between(p_finish, a_finish) if (p_finish and a_finish) else 0

        rows.append({
            "seq": int(m.get("seq") or 0),
            "code": code,
            "name": m.get("name"),
            "category": m.get("category"),
            "owner_role": m.get("owner_role"),
            "planned_start": p_start.isoformat() if p_start else None,
            "planned_finish": p_finish.isoformat() if p_finish else None,
            "actual_start": a_start,
            "actual_finish": a_finish,
            "forecast_finish": (a_finish or ov.get("revised_finish")
                                or (p_finish.isoformat() if p_finish else None)),
            "revised_finish": ov.get("revised_finish"),
            "status": None,
            "delay_days": delay,
            "delay_reason": ov.get("delay_reason"),
            "is_critical": bool(m.get("is_critical")),
            "calendar": mcid,
            "depends_on": list(m.get("depends_on") or []),
            "evidence_source": m.get("evidence_source"),
            "evidence_value": evidence_value,
            "offset_days": offset,
            "duration_days": dur,
            "requires_approval": bool(m.get("requires_approval")),
            "is_blocked": False,
            "blocked_by": [],
            "status_source": "override" if ov.get("status_override") else "computed",
            "needs_attribution": bool(delay > 0 and not ov.get("delay_reason")),
            "owner": ov.get("owner") or m.get("owner_role"),
            "note": ov.get("note"),
            "manual": not bool(m.get("evidence_source")),
            "evidence_retrieved": retrieved,
            "data_source": data_source,
            "updated_at": ov.get("updated_at"),
            "status_override": ov.get("status_override"),
        })

    # Status pass — dependencies always point to an earlier seq, so a single
    # forward pass has every predecessor status available.
    rows.sort(key=lambda r: r["seq"])
    status_by_code: dict = {}
    defs_by_code = {m.get("code"): m for m in defs}
    for r in rows:
        defn = defs_by_code.get(r["code"]) or {}
        status, status_source, blocked_by, is_blocked = derive_status(
            r, defn, r["planned_start"], r["planned_finish"], today, cal,
            status_by_code, category_by_code, config.NOT_RECORDED_CODES, config.AT_RISK_WINDOW_WD,
        )
        r["status"] = status
        r["status_source"] = status_source
        r["blocked_by"] = blocked_by
        r["is_blocked"] = bool(is_blocked)
        r["needs_attribution"] = bool(int(r.get("delay_days") or 0) > 0 and not r.get("delay_reason"))
        status_by_code[r["code"]] = status

    # Critical path + float over the dependency graph (replaces the hardcoded flag).
    _compute_cpm(rows, template.get("anchor") or "SHIP", cal)

    # Progress — per milestone and duration-weighted at the order level.
    order_qty = order.get("qty") or 0
    wsum = 0.0
    wtot = 0.0
    for r in rows:
        act = actuals.get(r["code"]) or {}
        r["progress_pct"] = _progress_pct(r, act.get("qty"), order_qty)
        w = max(1, int(r.get("duration_days") or 1))
        wsum += r["progress_pct"] * w
        wtot += w
    order_progress = round(wsum / wtot, 1) if wtot else 0.0

    k = kpis(rows, {**order, "ship_date": ship}, cal, today_iso)
    k["source"] = source
    k["progress_pct"] = order_progress
    k["erp_linked_count"] = sum(1 for r in rows if r.get("data_source") == "erp")
    k["manual_count"] = sum(1 for r in rows if r.get("manual"))

    ex = build_exceptions(rows)
    alerts = build_alerts(rows, today_iso, cal, config.ESCALATION_L1_WD, config.ESCALATION_L2_WD)
    owners = build_owner_workload(rows)
    a_summary = alert_summary(alerts, len(rows))
    k["alert_count"] = len(alerts)
    k["alert_critical_count"] = a_summary["critical"]
    k["max_escalation"] = a_summary["max_escalation"]

    header = {
        "order_id": order.get("sales_order"),
        "sales_order_status": order.get("sales_order_status"),
        "docstatus": order.get("docstatus"),
        "customer": order.get("customer"),
        "customer_legal": order.get("customer_legal"),
        "company": order.get("company"),
        "po_no": order.get("po_no"),
        "client_po_no": order.get("client_po_no"),
        "po_date": order.get("po_date"),
        "style_no": order.get("style_no"),
        "style_name": order.get("style_name"),
        "colour": order.get("colour"),
        "qty": order.get("qty"),
        "sizes": order.get("sizes") or {},
        "order_value": order.get("grand_total"),
        "currency": order.get("currency"),
        "site": order.get("site"),
        "ship_date": ship,
        "days_to_ship": k.get("days_to_ship"),
        "overall_status": _overall_status(k),
        "rag": k.get("rag"),
        "calendar": cid,
        "default_calendar": cid,
        "product_type": template.get("template_id") or config.DEFAULT_PRODUCT_TYPE,
        "template_id": template.get("template_id") or config.DEFAULT_PRODUCT_TYPE,
        "source": source,
    }

    return {
        "source": source,
        "as_of": today_iso,
        "header": header,
        "milestones": rows,
        "kpis": k,
        "exceptions": ex,
        "alerts": alerts,
        "alert_summary": a_summary,
        "owners": owners,
        "calendar": cal_data if "error" not in cal_data else load_holidays(cid),
        "template": {"template_id": template.get("template_id"),
                     "product_type": template.get("product_type"),
                     "milestone_count": template.get("milestone_count")},
        "data_quality": list(norm.get("data_quality") or []),
        "warnings": list(norm.get("warnings") or []),
    }


def _overall_status(k: dict) -> str:
    if k.get("overdue_count"):
        return "Overdue"
    if k.get("blocked_count"):
        return "Blocked"
    if k.get("at_risk_count"):
        return "At risk"
    if k.get("not_recorded_count"):
        return "Not recorded"
    if k.get("in_progress_count") or k.get("waiting_approval_count") or k.get("waiting_material_count"):
        return "In progress"
    if k.get("not_started_count"):
        return "Not started"
    return "On track"


def overlay_index(rows) -> dict:
    """Build the ``code -> overlay`` mapping `build_calendar` consumes from ORM rows."""
    out: dict = {}
    for r in rows or []:
        code = getattr(r, "milestone_code", None) or (r.get("milestone_code") if isinstance(r, dict) else None)
        if not code:
            continue
        if isinstance(r, dict):
            d = dict(r)
        else:
            d = r.to_dict()
        out[code] = d
    return out
