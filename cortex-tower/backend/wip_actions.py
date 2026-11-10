"""Cortex Operations Control Tower — the four things a planner does to a WIP plan.

The client's requirement, 2026-11-03: *"when a new order comes u dont do it, just that have a tab something where
we can discuss and then plan the chart and finalise"*. So the writer proposes and a human decides:

    comment(wip, text)                  the discussion — written to the ERP as a `Comment` on the WIP, so it is
                                        visible on the WIP form as well as in the Tower
    finalise(wip)                        Draft → Planned. The proposal becomes the plan. Refuses anything else.
    adjust(wip, plant, ship_date, pcd)   re-baseline: move the ship date / plant and shift every OPEN gate by the
                                        same delta, keeping every `actual` where it is
    reject(wip, reason)                  → Superseded, with the reason on the record (never deleted: a plan that
                                        was proposed and refused is history)

Every one of them is:
  * **mode-gated** — `writes.current_mode()`; `off` refuses everything, and the refusal says so;
  * **narrow** — it touches only the fields listed here, never the milestones' actuals;
  * **audited** — every call leaves a `Comment` on the record naming who did what and why.

Nothing here submits, cancels or deletes an ERP document.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote as _quote

import erp
import writes

WIP = "Cortex WIP"


class Refused(Exception):
    """A gate said no, with a reason a human can act on."""


def _gate(action: str) -> str:
    mode = writes.current_mode()
    if mode == "off":
        raise Refused(f"ERP writes are off (ERP_WRITE_MODE=off) — '{action}' was not sent. "
                      f"Set ERP_WRITE_MODE=draft to let the Tower plan and finalise.")
    return mode


def _doc(name: str) -> dict:
    ok, payload = erp._request(f"/api/resource/{WIP}/{_quote(name)}")
    if not ok or not (payload or {}).get("data"):
        raise Refused(f"{name} could not be read from the ERP")
    return payload["data"]


def _d(v) -> date | None:
    s = str(v or "")[:10]
    return date.fromisoformat(s) if len(s) == 10 else None


def _say(name: str, text: str) -> None:
    """One Comment row on the WIP — the discussion thread, and the audit trail, in one place."""
    erp.erp_create("Comment", {
        "doctype": "Comment", "comment_type": "Comment", "comment_email": "control-tower",
        "reference_doctype": WIP, "reference_name": name, "content": text,
    })


def thread(name: str, limit: int = 60) -> list[dict]:
    """The discussion on one WIP, oldest last. Read-only."""
    rows = erp.erp_get("Comment",
                       fields=["content", "owner", "creation", "comment_type"],
                       filters=[["reference_doctype", "=", WIP], ["reference_name", "=", name]],
                       limit=limit, order="creation desc")
    return [{"text": r.get("content") or "", "by": r.get("owner") or "", "at": (r.get("creation") or "")[:19]}
            for r in rows]


def comment(wip: str, text: str) -> dict:
    mode = _gate("comment")
    if not (text or "").strip():
        raise Refused("an empty comment is not a decision — write what was agreed")
    _doc(wip)
    _say(wip, text.strip())
    return {"wip": wip, "ok": True, "mode": mode, "message": "comment added"}


def finalise(wip: str, note: str = "") -> dict:
    """Draft → Planned. The one transition that turns a proposal into the plan the reports read."""
    mode = _gate("finalise")
    doc = _doc(wip)
    status = doc.get("status") or ""
    if status == "Planned":
        return {"wip": wip, "ok": True, "mode": mode, "message": "already planned — nothing to do"}
    if status != "Draft":
        raise Refused(f"{wip} is '{status}' — only a Draft proposal can be finalised "
                      f"(a live plan is changed with adjust, not finalised)")
    open_gates = [m for m in doc.get("milestones") or [] if (m.get("status") or "") not in ("Done", "Waived")]
    payload = {"status": "Planned",
               "remarks": ((doc.get("remarks") or "").strip() + " | finalised in the Control Tower"
                           + (f": {note.strip()}" if note.strip() else "")).strip(" |")}
    erp.erp_update(WIP, wip, payload)
    _say(wip, f"**plan finalised** by the planner — {len(doc.get('lines') or [])} SKU line(s), "
              f"{len(open_gates)} open gate(s), plant {doc.get('plant') or '—'}, "
              f"ship {str(doc.get('ship_date'))[:10]}"
              + (f". {note.strip()}" if note.strip() else ""))
    return {"wip": wip, "ok": True, "mode": mode, "status": "Planned",
            "message": f"{wip} finalised — the plan is now live"}


def adjust(wip: str, plant: str | None = None, ship_date: str | None = None, pcd: str | None = None,
           note: str = "", shift_open: bool = True) -> dict:
    """Re-baseline a plan: a new ship date and/or plant, with the open gates shifted by the same delta.

    A gate that is `Done` keeps its `actual` and is never moved — the evidence is history. Only the gates that
    have not happened yet move, which is what "re-plan the rest of it" means.
    """
    mode = _gate("adjust")
    doc = _doc(wip)
    old_ship = _d(doc.get("ship_date"))
    new_ship = _d(ship_date) if ship_date else old_ship
    if not new_ship:
        raise Refused("a plan needs a ship date")
    delta = (new_ship - old_ship).days if old_ship else 0
    new_plant = plant or doc.get("plant")
    new_pcd = _d(pcd) if pcd else (new_ship - timedelta(days=_lead(new_plant)) if new_ship else None)

    payload: dict = {"plant": new_plant, "ship_date": new_ship.isoformat(),
                     "pcd": new_pcd.isoformat() if new_pcd else None}
    moved = 0
    if shift_open and delta:
        rows = []
        for m in doc.get("milestones") or []:
            row = {k: m.get(k) for k in ("item_code", "milestone", "sequence", "department", "planned",
                                         "drop_dead", "actual", "critical", "status", "late_days",
                                         "responsible", "source", "remarks")}
            if (m.get("status") or "") not in ("Done", "Waived"):
                for f in ("planned", "drop_dead"):
                    v = _d(m.get(f))
                    if v:
                        row[f] = (v + timedelta(days=delta)).isoformat()
                if row.get("status") == "Late":
                    due = _d(row.get("drop_dead"))
                    row["late_days"] = max(0, (date.today() - due).days) if due else 0
                    row["status"] = "Late" if due and due < date.today() else "Pending"
                moved += 1
            rows.append({"doctype": "Cortex WIP Milestone", **row})
        payload["milestones"] = rows

    # the roll-up the desk would recompute on save
    late = [r for r in (payload.get("milestones") or doc.get("milestones") or [])
            if (r.get("status") or "") == "Late"]
    open_dates = [r.get("drop_dead") for r in (payload.get("milestones") or doc.get("milestones") or [])
                  if (r.get("status") or "") not in ("Done", "Waived") and _d(r.get("drop_dead"))]
    payload["late_count"] = len(late)
    payload["next_due"] = min(open_dates).isoformat() if open_dates and hasattr(min(open_dates), "isoformat") \
        else (min(open_dates) if open_dates else None)

    erp.erp_update(WIP, wip, payload)
    _say(wip, f"**plan adjusted** — ship {str(doc.get('ship_date'))[:10]} → {new_ship.isoformat()}"
              f" ({delta:+d} day(s)), plant {doc.get('plant') or '—'} → {new_plant or '—'}, "
              f"{moved} open gate(s) shifted" + (f". {note.strip()}" if note.strip() else ""))
    return {"wip": wip, "ok": True, "mode": mode, "delta_days": delta, "moved_gates": moved,
            "ship_date": new_ship.isoformat(), "plant": new_plant,
            "message": f"{wip} re-baselined ({delta:+d} day(s), {moved} gate(s) moved)"}


def reject(wip: str, reason: str = "") -> dict:
    mode = _gate("reject")
    doc = _doc(wip)
    if (doc.get("status") or "") not in ("Draft",):
        raise Refused(f"{wip} is '{doc.get('status')}' — only a Draft proposal can be rejected")
    erp.erp_update(WIP, wip, {"status": "Superseded",
                              "remarks": ((doc.get("remarks") or "").strip() + " | rejected: "
                                          + (reason.strip() or "no reason given")).strip(" |")})
    _say(wip, f"**proposal rejected** — {reason.strip() or 'no reason given'}")
    return {"wip": wip, "ok": True, "mode": mode, "message": f"{wip} superseded"}


def _lead(plant: str | None) -> int:
    if not plant:
        return 0
    rows = erp.erp_get("Plant Floor", fields=["standard_production_lead_time_days"],
                       filters=[["name", "=", plant]], limit=1)
    try:
        return int(float(rows[0].get("standard_production_lead_time_days") or 0)) if rows else 0
    except (TypeError, ValueError, IndexError):
        return 0


def apply_plan(wip: str, changes: str = "", ship_date: str = "", note: str = "") -> dict:
    """Write the dates a planner settled on — the gate-by-gate version of `adjust`.

    `changes` is `"Gate=YYYY-MM-DD;Gate two=YYYY-MM-DD"`: the dates the **Plan tab** computed after the planner
    pressed `+` / `−`. The arithmetic happens where the planner can see it (the browser); this only writes, and
    it refuses to write something the record cannot hold:

      * an unknown gate name → refused, listing the gates the record actually has;
      * a gate whose rows are `Done` → **not moved**, and said so in the reply. An actual is history: the plan
        may not rewrite what happened. (Moving a finished gate is a data correction, not a re-plan.)
      * a gate that is `Waived` → left alone for the same reason.

    Every open row of a named gate gets the same date, so the plan stays one plan across the order's SKUs.
    The header's `late_count` and `next_due` are recomputed from the rows — never carried over.
    """
    mode = _gate("apply_plan")
    doc = _doc(wip)
    rows = doc.get("milestones") or []
    if not rows:
        raise Refused(f"{wip} has no milestone rows — there is no plan to change")

    wanted: dict[str, str] = {}
    for part in (changes or "").split(";"):
        if "=" not in part:
            continue
        name, _, val = part.rpartition("=")
        name, val = name.strip(), val.strip()[:10]
        if name and val:
            try:
                date.fromisoformat(val)
            except ValueError:
                raise Refused(f"'{val}' is not a date (expected YYYY-MM-DD) for {name}")
            wanted[name] = val
    if not wanted:
        raise Refused("no dates were sent — 'changes' must read Gate=YYYY-MM-DD;Gate2=YYYY-MM-DD")

    have = {r.get("milestone") for r in rows}
    unknown = [g for g in wanted if g not in have]
    if unknown:
        raise Refused(f"{wip} has no gate called {', '.join(unknown)}. Gates on this plan: "
                      f"{', '.join(sorted(g for g in have if g))}")

    today = date.today()
    out_rows, moved, kept = [], 0, []
    for r in rows:
        row = {k: r.get(k) for k in ("item_code", "milestone", "sequence", "department", "planned", "drop_dead",
                                     "actual", "critical", "status", "late_days", "responsible", "source",
                                     "remarks", "phase", "phase_name", "evidence_doctype")}
        gate = r.get("milestone")
        if gate in wanted:
            if (r.get("status") or "") in ("Done", "Waived") or r.get("actual"):
                kept.append(gate)
            else:
                new = wanted[gate]
                row["planned"] = new
                row["drop_dead"] = new
                due = date.fromisoformat(new)
                row["status"] = "Late" if due < today else "Pending"
                row["late_days"] = max(0, (today - due).days)
                row["nudge_days"] = (due - (date.fromisoformat(str(r.get("drop_dead"))[:10])
                                            if r.get("drop_dead") else due)).days
                row["source"] = "planned in the Tower"
                moved += 1
        out_rows.append({"doctype": "Cortex WIP Milestone", **row})

    open_dates = [x["drop_dead"] for x in out_rows if x.get("drop_dead")
                  and (x.get("status") or "") not in ("Done", "Waived")]
    payload = {
        "milestones": out_rows,
        "late_count": sum(1 for x in out_rows if x.get("status") == "Late"),
        "next_due": min(open_dates) if open_dates else None,
    }
    new_ship = _d(ship_date) if ship_date else _d(doc.get("ship_date"))
    if ship_date:
        if not new_ship:
            raise Refused(f"'{ship_date}' is not a date")
        payload["ship_date"] = new_ship.isoformat()
    # the lines' own roll-up follows the plan, so the list view and the Gantt never disagree
    by_item: dict[str, list] = {}
    for x in out_rows:
        by_item.setdefault(x.get("item_code") or "", []).append(x)
    lines = []
    for ln in doc.get("lines") or []:
        mine = by_item.get(ln.get("item_code") or "", [])
        openm = [x for x in mine if (x.get("status") or "") not in ("Done", "Waived") and x.get("drop_dead")]
        done = [x for x in mine if (x.get("status") or "") == "Done"]
        nxt = min(openm, key=lambda x: x["drop_dead"]) if openm else None
        lines.append({**{k: ln.get(k) for k in ("item_code", "qty", "cut_qty", "shipped_qty", "plant", "colour",
                                               "size")},
                      "doctype": "Cortex WIP Line",
                      "current_stage": done[-1]["milestone"] if done else "",
                      "next_milestone": nxt["milestone"] if nxt else "",
                      "next_due": nxt["drop_dead"] if nxt else None,
                      "late": 1 if any(x.get("status") == "Late" for x in mine) else 0,
                      "pct_complete": round(100.0 * len(done) / len(mine), 1) if mine else 0})
    payload["lines"] = lines

    erp.erp_update(WIP, wip, payload)
    gist = "; ".join(f"{g} → {d}" for g, d in list(wanted.items())[:6])
    _say(wip, f"**plan re-dated** — {moved} open gate row(s) moved ({gist}"
              + (f", +{len(wanted) - 6} more" if len(wanted) > 6 else "") + ")"
              + (f". Not moved because the work is already recorded: {', '.join(sorted(set(kept)))}" if kept else "")
              + (f". {note.strip()}" if note.strip() else ""))

    return {"wip": wip, "ok": True, "mode": mode, "gates_sent": len(wanted), "rows_moved": moved,
            "gates_kept_done": sorted(set(kept)), "late_count": payload["late_count"],
            "next_due": payload["next_due"], "ship_date": payload.get("ship_date") or _d(doc.get("ship_date")),
            "message": f"{wip}: {moved} row(s) re-dated across {len(wanted)} gate(s)"}
