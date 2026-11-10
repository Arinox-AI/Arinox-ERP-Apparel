"""The milestone template as the scheduler's input: ERP codes, typed lags derived from the template's own offsets, ERP-only tasks added.

The tower's 61-milestone JSON states each milestone's FINISH as an offset in working days from SHIP (= the ex-factory date) and its
predecessors. The scheduler needs links with lags, so the lag of each link is read off the template itself: the working days
strictly between the predecessor's finish and the successor's start. That makes the baseline of an order exactly the template, and
lets a late predecessor move its successors.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Optional

from . import vocab
from .calendars import WorkingCalendar, load_calendars

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(os.path.dirname(HERE), "tna_app", "data", "tna_template_woven_shirt.json")
REF = date(2030, 1, 1)                      # any date: lags are differences, the template has no absolute dates


def lag_type(pred: dict, succ: dict, lag: int) -> str:
    if lag < 0:
        return "overlap"
    n = (succ["name"] + pred["name"]).lower()
    if any(w in n for w in ("approv", "comment", "sign")):
        return "approval"
    if any(w in n for w in ("handover", "bl ", "delivery", "dispatch", "etd", "transit", "ship")):
        return "transit"
    return "wait" if lag else "buffer"


def load(path: str = "", calendars: Optional[dict[str, WorkingCalendar]] = None) -> dict:
    raw = json.load(open(path or TEMPLATE_PATH))
    cals = calendars or load_calendars()
    rows = raw["milestones"]
    by = {r["code"]: r for r in rows}
    tasks: dict[str, dict] = {}
    for r in rows:
        tasks[vocab.erp_code(r["code"])] = {
            "code": vocab.erp_code(r["code"]), "tower_code": r["code"], "name": r["name"], "category": r.get("category"), "owner_role": r.get("owner_role"),
            "calendar": r.get("calendar") or "VN_FACTORY", "duration": int(r.get("duration_days") or 0), "offset": int(r.get("offset_days") or 0),
            "is_critical": bool(r.get("is_critical")), "requires_approval": bool(r.get("requires_approval")), "evidence_source": r.get("evidence_source") or "",
            "preds": [vocab.erp_code(p) for p in r.get("depends_on") or []], "seq": int(r.get("seq") or 0)}
    # ERP-only tasks (FABRIC_ETD, PCD): spliced between their neighbours, offset = their predecessor's finish offset (no extra time)
    for code, spec in vocab.ERP_ONLY_TASKS.items():
        after = [vocab.erp_code(a) for a in spec["after"]]
        before = [vocab.erp_code(b) for b in spec["before"]]
        off = max(tasks[a]["offset"] for a in after)
        t = {"code": code, "tower_code": code, "name": spec["name"], "category": spec["category"], "owner_role": spec["owner_role"], "calendar": spec["calendar"],
             "duration": spec["duration"], "offset": off, "is_critical": spec["is_critical"], "requires_approval": False, "evidence_source": "", "preds": after,
             "seq": 0, "pinned_anchor": bool(spec.get("pinned_anchor"))}
        tasks[code] = t
        for b in before:
            tasks[b]["preds"] = [code if p in after else p for p in tasks[b]["preds"]] if any(p in after for p in tasks[b]["preds"]) else tasks[b]["preds"] + [code]
    # lags read off the template
    def finish(t):  # reference finish in the task's own calendar
        return cals[t["calendar"]].shift(REF, t["offset"])
    def start(t):
        c = cals[t["calendar"]]
        return c.shift(finish(t), -(t["duration"] - 1)) if t["duration"] > 0 else finish(t)
    for t in tasks.values():
        links = []
        for p in t["preds"]:
            pt = tasks[p]
            sc = cals[t["calendar"]]
            pf, ts = finish(pt), start(t)
            lag = sc.between(pf, ts) - 1 if ts > pf else sc.between(pf, ts) - 1
            links.append({"pred": p, "type": "FS", "lag": lag, "lag_type": lag_type(pt, t, lag)})
        t["links"] = links
    return {"template_id": raw.get("template_id"), "calendar": raw.get("calendar"), "tasks": tasks, "order": [vocab.erp_code(r["code"]) for r in rows],
            "categories": raw.get("categories"), "anchor": "SHIP"}
